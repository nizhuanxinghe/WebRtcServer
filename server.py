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
        @channel.on("message")
        def on_message(message):
            if isinstance(message, str) and message.startswith("ping"):
                channel.send("pong" + message[4:])

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        log_info("Connection state is %s", pc.connectionState)
        if pc.connectionState == "failed":
            await pc.close()
            pcs.discard(pc)

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
    await pc.setRemoteDescription(offer)
    
    # send video
    if player.video:
        pc.addTrack(player.video)
    if player.audio:
        pc.addTrack(player.audio)

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

    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.TEXT:
            data = json.loads(msg.data)

            if data.get("type") == "offer":
                offer = RTCSessionDescription(sdp=data["sdp"], type=data["type"])
                await pc.setRemoteDescription(offer)

                # send video
                if player.video:
                    pc.addTrack(player.video)
                if player.audio:
                    pc.addTrack(player.audio)

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
    import socket
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
