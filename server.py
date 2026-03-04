import argparse
import asyncio
import json
import logging
import os
import ssl
import uuid

import aiohttp
from aiohttp import web
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription, RTCIceCandidate
from aiortc.contrib.media import MediaPlayer, MediaRelay
import socket

ROOT = os.path.dirname(__file__)

logger = logging.getLogger("pc")
pcs = set()
relay = MediaRelay()

async def index(request):
    content = open(os.path.join(ROOT, "index.html"), "r").read()
    return web.Response(content_type="text/html", text=content)

async def javascript(request):
    content = open(os.path.join(ROOT, "client.js"), "r").read()
    return web.Response(content_type="application/javascript", text=content)

async def offer(request):
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    pc = RTCPeerConnection()
    pc_id = "PeerConnection(%s)" % uuid.uuid4()
    pcs.add(pc)

    def log_info(msg, *args):
        logger.info(pc_id + " " + msg, *args)

    log_info("Created for %s", request.remote)

    # prepare local media
    player = MediaPlayer(os.path.join(ROOT, "夏日初见.mov"))
    
    @pc.on("datachannel")
    def on_datachannel(channel):
        log_info("DataChannel received: %s", channel.label)

        @channel.on("message")
        def on_message(message):
            log_info("Received message: %s", message)
            if isinstance(message, str):
                if message.startswith("ping"):
                    channel.send("pong" + message[4:])
                else:
                    channel.send("echo: " + message)

    data_channel = pc.createDataChannel("data")
    @data_channel.on("open")
    def on_data_channel_open():
        log_info("DataChannel opened: %s", data_channel.label)
        data_channel.send("Hello from server!")

    @data_channel.on("message")
    def on_data_channel_message(message):
        log_info("DataChannel message received: %s", message)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        log_info("Connection state is %s", pc.connectionState)
        if pc.connectionState == "failed":
            await pc.close()
            pcs.discard(pc)

    @pc.on("icegatheringstatechange")
    async def on_icegatheringstatechange():
        log_info("ICE gathering state: %s", pc.iceGatheringState)

    @pc.on("track")
    def on_track(track):
        log_info("Track %s received", track.kind)
        if track.kind == "audio":
            pc.addTrack(player.audio)
        elif track.kind == "video":
            pc.addTrack(player.video)

        @track.on("ended")
        async def on_ended():
            log_info("Track %s ended", track.kind)
            await pc.close()
            pcs.discard(pc)

    # handle offer
    # add tracks BEFORE setting remote description
    if player.video:
        pc.addTrack(player.video)
        log_info("Added video track")
    if player.audio:
        pc.addTrack(player.audio)
        log_info("Added audio track")

    await pc.setRemoteDescription(offer)

    # send answer
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
        ),
    )

async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    pc = RTCPeerConnection()
    pc_id = "PeerConnection(%s)" % uuid.uuid4()
    pcs.add(pc)

    def log_info(msg, *args):
        logger.info(pc_id + " " + msg, *args)

    log_info("WebSocket connected from %s", request.remote)

    # prepare local media
    player = MediaPlayer(os.path.join(ROOT, "夏日初见.mov"))

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        log_info("Connection state is %s", pc.connectionState)
        if pc.connectionState == "failed":
            await pc.close()
            pcs.discard(pc)

    @pc.on("icegatheringstatechange")
    async def on_icegatheringstatechange():
        log_info("ICE gathering state: %s", pc.iceGatheringState)

    @pc.on("icecandidate")
    async def on_icecandidate(candidate):
        log_info("ICE candidate: %s", candidate)
        if candidate:
            await ws.send_str(json.dumps({
                "type": "candidate",
                "candidate": candidate.candidate,
                "sdpMid": candidate.sdpMid,
                "sdpMLineIndex": candidate.sdpMLineIndex
            }))

    @pc.on("datachannel")
    def on_datachannel(channel):
        log_info("DataChannel received: %s", channel.label)

        @channel.on("message")
        def on_message(message):
            log_info("Received message from client: %s", message)
            if isinstance(message, str):
                if message.startswith("ping"):
                    channel.send("pong" + message[4:])
                else:
                    channel.send("echo: " + message)

    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.TEXT:
            data = json.loads(msg.data)

            if data.get("type") == "offer":
                offer = RTCSessionDescription(sdp=data["sdp"], type=data["type"])

                log_info("Received offer, adding local tracks first")

                # send video/audio BEFORE setting remote description
                if player.video:
                    pc.addTrack(player.video)
                    log_info("Added video track")
                if player.audio:
                    pc.addTrack(player.audio)
                    log_info("Added audio track")

                # now set remote description
                await pc.setRemoteDescription(offer)

                # create data channel for sending data
                data_channel = pc.createDataChannel("data")
                @data_channel.on("open")
                def on_data_channel_open():
                    log_info("DataChannel opened: %s", data_channel.label)
                    data_channel.send("Hello from server via WebSocket!")

                @data_channel.on("message")
                def on_data_channel_message(message):
                    log_info("DataChannel message received: %s", message)
                    data_channel.send("echo: " + str(message))

                # create and set local description
                answer = await pc.createAnswer()
                await pc.setLocalDescription(answer)

                response = {
                    "sdp": pc.localDescription.sdp,
                    "type": pc.localDescription.type
                }
                await ws.send_str(json.dumps(response))
            
            elif data.get("type") == "candidate":
                candidate_info = data.get("candidate") or data.get("sdp")
                sdp_mid = data.get("sdpMid") or data.get("id")
                sdp_mline_index = data.get("sdpMLineIndex") or data.get("label")
                
                if candidate_info:
                    candidate = RTCIceCandidate(
                        candidate=candidate_info,
                        sdpMid=sdp_mid,
                        sdpMLineIndex=sdp_mline_index
                    )
                    await pc.addIceCandidate(candidate)
    
    # cleanup
    await pc.close()
    pcs.discard(pc)
    return ws

async def on_shutdown(app):
    # close peer connections
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()

if __name__ == "__main__":
    print("Starting server...")
    logging.basicConfig(level=logging.INFO)
    app = web.Application()
    app.on_shutdown.append(on_shutdown)
    app.router.add_get("/", index)
    app.router.add_get("/client.js", javascript)
    app.router.add_post("/offer", offer)
    app.router.add_get("/ws", websocket_handler)

    def get_local_ip():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"

    ip = get_local_ip()
    print(f"Server started at http://{ip}:8080")
    print(f"Signaling URL (HTTP): http://{ip}:8080/offer")
    print(f"Signaling URL (WebSocket): ws://{ip}:8080/ws")
    web.run_app(app, access_log=None, host="0.0.0.0", port=8080)
