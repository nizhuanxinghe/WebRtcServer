package com.example.webrtcdemo

import android.content.Context
import android.util.Log
import org.webrtc.AudioSource
import org.webrtc.AudioTrack
import org.webrtc.Camera1Enumerator
import org.webrtc.Camera2Enumerator
import org.webrtc.CameraEnumerator
import org.webrtc.DataChannel
import org.webrtc.DefaultVideoDecoderFactory
import org.webrtc.DefaultVideoEncoderFactory
import org.webrtc.EglBase
import org.webrtc.IceCandidate
import org.webrtc.MediaConstraints
import org.webrtc.MediaStream
import org.webrtc.PeerConnection
import org.webrtc.PeerConnectionFactory
import org.webrtc.RtpReceiver
import org.webrtc.SdpObserver
import org.webrtc.SessionDescription
import org.webrtc.SurfaceTextureHelper
import org.webrtc.SurfaceViewRenderer
import org.webrtc.VideoCapturer
import org.webrtc.VideoDecoderFactory
import org.webrtc.VideoEncoderFactory
import org.webrtc.VideoSource
import org.webrtc.VideoTrack
import org.webrtc.audio.AudioDeviceModule
import org.webrtc.audio.JavaAudioDeviceModule
import java.util.Collections

class WebRTCManager(private val context: Context) {

    private val rootEgl: EglBase = EglBase.create()
    private var factory: PeerConnectionFactory? = null
    private var peerConnection: PeerConnection? = null
    private var videoCapturer: VideoCapturer? = null
    private var videoSource: VideoSource? = null
    private var audioSource: AudioSource? = null
    private var localVideoTrack: VideoTrack? = null
    private var localAudioTrack: AudioTrack? = null
    private var signalingClient: SignalingClient? = null
    private var remoteRenderer: SurfaceViewRenderer? = null

    init {
        initWebRTC()
        createPeerConnectionFactory()
    }

    private fun initWebRTC() {
        val initOptions = PeerConnectionFactory.InitializationOptions.builder(context)
            .setEnableInternalTracer(true)
            .setFieldTrials("WebRTC-H264HighProfile/Enabled/")
            .createInitializationOptions()
        PeerConnectionFactory.initialize(initOptions)
    }

    private fun createPeerConnectionFactory() {
        val encoderFactory: VideoEncoderFactory = DefaultVideoEncoderFactory(
            rootEgl.eglBaseContext, true, true
        )
        val decoderFactory: VideoDecoderFactory = DefaultVideoDecoderFactory(rootEgl.eglBaseContext)

        val adm: AudioDeviceModule = JavaAudioDeviceModule.builder(context)
            .createAudioDeviceModule()

        val options = PeerConnectionFactory.Options()

        factory = PeerConnectionFactory.builder()
            .setOptions(options)
            .setAudioDeviceModule(adm)
            .setVideoEncoderFactory(encoderFactory)
            .setVideoDecoderFactory(decoderFactory)
            .createPeerConnectionFactory()
    }

    fun initRenderer(renderer: SurfaceViewRenderer) {
        renderer.init(rootEgl.eglBaseContext, null)
        renderer.setMirror(false)
        renderer.setEnableHardwareScaler(true)
        this.remoteRenderer = renderer
    }

    fun startCapture(localRenderer: SurfaceViewRenderer) {
        localRenderer.init(rootEgl.eglBaseContext, null)
        localRenderer.setMirror(true)
        localRenderer.setEnableHardwareScaler(true)

        factory?.let { factory ->
            // Create Video Track
            val surfaceHelper = SurfaceTextureHelper.create("CaptureThread", rootEgl.eglBaseContext)
            val enumerator: CameraEnumerator = if (Camera2Enumerator.isSupported(context)) {
                Camera2Enumerator(context)
            } else {
                Camera1Enumerator(true)
            }
            
            val deviceNames = enumerator.deviceNames
            val camName = deviceNames.find { enumerator.isFrontFacing(it) } ?: deviceNames.firstOrNull()
            
            camName?.let { name ->
                videoCapturer = enumerator.createCapturer(name, null)
                videoSource = factory.createVideoSource(videoCapturer!!.isScreencast)
                videoCapturer?.initialize(surfaceHelper, context, videoSource!!.capturerObserver)
                videoCapturer?.startCapture(1280, 720, 30)

                localVideoTrack = factory.createVideoTrack("ARDAMSv0", videoSource)
                localVideoTrack?.addSink(localRenderer)
            }

            // Create Audio Track
            audioSource = factory.createAudioSource(MediaConstraints())
            localAudioTrack = factory.createAudioTrack("ARDAMSa0", audioSource)
        }
    }

    fun startCall(signalingUrl: String) {
        if (peerConnection == null) {
            createPeerConnection()
        }
        
        signalingClient = SignalingClient(signalingUrl, object : SignalingClient.Callback {
            override fun onConnected() {
                Log.d("WebRTCManager", "Connected to signaling server")
                // Usually we might send "ready" or create offer here if we are the caller
                // For simplicity, let's assume we create an offer immediately if we are the initiator
                // But typically, the one who clicks "Call" creates the offer.
                // Let's assume we are always the caller for now if we start the call.
                createOffer()
            }

            override fun onOfferReceived(sdp: String) {
                Log.d("WebRTCManager", "Offer received")
                setRemoteDescription(SessionDescription.Type.OFFER, sdp)
                createAnswer()
            }

            override fun onAnswerReceived(sdp: String) {
                Log.d("WebRTCManager", "Answer received")
                setRemoteDescription(SessionDescription.Type.ANSWER, sdp)
            }

            override fun onIceCandidateReceived(sdpMid: String, sdpMLineIndex: Int, candidate: String) {
                Log.d("WebRTCManager", "ICE Candidate received")
                val iceCandidate = IceCandidate(sdpMid, sdpMLineIndex, candidate)
                peerConnection?.addIceCandidate(iceCandidate)
            }

            override fun onDisconnected() {
                Log.d("WebRTCManager", "Signaling disconnected")
            }

            override fun onError(message: String) {
                Log.e("WebRTCManager", "Signaling error: $message")
            }
        })
        signalingClient?.connect()
    }

    private fun createPeerConnection() {
        factory?.let { factory ->
            val iceServers = listOf(
                PeerConnection.IceServer.builder("stun:stun.l.google.com:19302").createIceServer()
            )

            val rtcConfig = PeerConnection.RTCConfiguration(iceServers)
            
            val observer = object : PeerConnection.Observer {
                override fun onSignalingChange(state: PeerConnection.SignalingState?) {}
                override fun onIceConnectionChange(state: PeerConnection.IceConnectionState?) {}
                override fun onIceConnectionReceivingChange(receiving: Boolean) {}
                override fun onIceGatheringChange(state: PeerConnection.IceGatheringState?) {}
                
                override fun onIceCandidate(candidate: IceCandidate?) {
                    candidate?.let {
                        signalingClient?.sendIceCandidate(it.sdpMid, it.sdpMLineIndex, it.sdp)
                    }
                }
                
                override fun onIceCandidatesRemoved(candidates: Array<out IceCandidate>?) {}
                
                override fun onAddStream(stream: MediaStream?) {
                    // Deprecated, but sometimes used. Prefer onAddTrack.
                }
                
                override fun onRemoveStream(stream: MediaStream?) {}
                override fun onDataChannel(dataChannel: DataChannel?) {}
                override fun onRenegotiationNeeded() {}
                
                override fun onAddTrack(receiver: RtpReceiver?, mediaStreams: Array<out MediaStream>?) {
                    receiver?.track()?.let { track ->
                        if (track.kind() == "video") {
                            val videoTrack = track as VideoTrack
                            remoteRenderer?.let { renderer ->
                                videoTrack.addSink(renderer)
                            }
                        }
                    }
                }
            }

            peerConnection = factory.createPeerConnection(rtcConfig, observer)

            localVideoTrack?.let { videoTrack ->
                peerConnection?.addTrack(videoTrack, Collections.singletonList("ARDAMS"))
            }
            localAudioTrack?.let { audioTrack ->
                peerConnection?.addTrack(audioTrack, Collections.singletonList("ARDAMS"))
            }
        }
    }

    private fun createOffer() {
        peerConnection?.createOffer(object : SdpObserver {
            override fun onCreateSuccess(desc: SessionDescription?) {
                desc?.let {
                    peerConnection?.setLocalDescription(object : SdpObserver {
                        override fun onCreateSuccess(p0: SessionDescription?) {}
                        override fun onSetSuccess() {
                            signalingClient?.sendOffer(it.description)
                        }
                        override fun onCreateFailure(p0: String?) {}
                        override fun onSetFailure(p0: String?) {}
                    }, it)
                }
            }
            override fun onSetSuccess() {}
            override fun onCreateFailure(error: String?) {}
            override fun onSetFailure(error: String?) {}
        }, MediaConstraints())
    }

    private fun createAnswer() {
        peerConnection?.createAnswer(object : SdpObserver {
            override fun onCreateSuccess(desc: SessionDescription?) {
                desc?.let {
                    peerConnection?.setLocalDescription(object : SdpObserver {
                        override fun onCreateSuccess(p0: SessionDescription?) {}
                        override fun onSetSuccess() {
                            signalingClient?.sendAnswer(it.description)
                        }
                        override fun onCreateFailure(p0: String?) {}
                        override fun onSetFailure(p0: String?) {}
                    }, it)
                }
            }
            override fun onSetSuccess() {}
            override fun onCreateFailure(error: String?) {}
            override fun onSetFailure(error: String?) {}
        }, MediaConstraints())
    }

    private fun setRemoteDescription(type: SessionDescription.Type, sdp: String) {
        val sessionDescription = SessionDescription(type, sdp)
        peerConnection?.setRemoteDescription(object : SdpObserver {
            override fun onCreateSuccess(p0: SessionDescription?) {}
            override fun onSetSuccess() {}
            override fun onCreateFailure(p0: String?) {}
            override fun onSetFailure(p0: String?) {}
        }, sessionDescription)
    }

    fun stopCall() {
        signalingClient?.close()
        signalingClient = null
        peerConnection?.close()
        peerConnection = null
    }

    fun release() {
        stopCall()
        try {
            videoCapturer?.stopCapture()
            videoCapturer?.dispose()
            videoSource?.dispose()
            audioSource?.dispose()
            factory?.dispose()
            rootEgl.release()
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }
    
    fun getEglBaseContext(): EglBase.Context {
        return rootEgl.eglBaseContext
    }
}
