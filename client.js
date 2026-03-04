var pc = null;
var dataChannel = null;

function logMessage(message, type) {
    var log = document.getElementById('messageLog');
    var div = document.createElement('div');
    div.className = type;
    div.textContent = message;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
}

function sendMessage() {
    var input = document.getElementById('messageInput');
    var message = input.value.trim();
    if (message && dataChannel && dataChannel.readyState === 'open') {
        dataChannel.send(message);
        logMessage('发送: ' + message, 'sent');
        input.value = '';
    } else {
        alert('DataChannel 未连接');
    }
}

document.getElementById('messageInput').addEventListener('keypress', function(e) {
    if (e.key === 'Enter') {
        sendMessage();
    }
});

function negotiate() {
    pc.addTransceiver('video', {direction: 'recvonly'});
    pc.addTransceiver('audio', {direction: 'recvonly'});

    return pc.createOffer().then(function(offer) {
        return pc.setLocalDescription(offer);
    }).then(function() {
        // wait for ICE gathering to complete
        return new Promise(function(resolve) {
            if (pc.iceGatheringState === 'complete') {
                resolve();
            } else {
                function checkState() {
                    if (pc.iceGatheringState === 'complete') {
                        pc.removeEventListener('icegatheringstatechange', checkState);
                        resolve();
                    }
                }
                pc.addEventListener('icegatheringstatechange', checkState);
            }
        });
    }).then(function() {
        var offer = pc.localDescription;
        return fetch('/offer', {
            body: JSON.stringify({
                sdp: offer.sdp,
                type: offer.type,
            }),
            headers: {
                'Content-Type': 'application/json'
            },
            method: 'POST'
        });
    }).then(function(response) {
        return response.json();
    }).then(function(answer) {
        return pc.setRemoteDescription(answer);
    }).catch(function(e) {
        alert(e);
    });
}

var videoElement = null;
var isPlaying = false;

function togglePlay() {
    var video = document.getElementById('video');
    var playButton = document.getElementById('play');

    if (isPlaying) {
        video.pause();
        playButton.textContent = '播放';
        playButton.style.backgroundColor = '#28a745';
    } else {
        video.play();
        playButton.textContent = '暂停';
        playButton.style.backgroundColor = '#ffc107';
        playButton.style.color = '#000';
    }
    isPlaying = !isPlaying;
}

function start() {
    var config = {
        sdpSemantics: 'unified-plan'
    };

    pc = new RTCPeerConnection(config);

    // create data channel
    dataChannel = pc.createDataChannel('data');
    dataChannel.onopen = function() {
        logMessage('DataChannel 已连接', 'received');
    };
    dataChannel.onmessage = function(event) {
        logMessage('收到: ' + event.data, 'received');
    };
    dataChannel.onclose = function() {
        logMessage('DataChannel 已关闭', 'received');
    };

    // handle incoming data channel from server
    pc.ondatachannel = function(event) {
        var receiveChannel = event.channel;
        receiveChannel.onmessage = function(event) {
            logMessage('收到: ' + event.data, 'received');
        };
        receiveChannel.onopen = function() {
            logMessage('服务器 DataChannel 已连接', 'received');
        };
        receiveChannel.onclose = function() {
            logMessage('服务器 DataChannel 已关闭', 'received');
        };
    };

    // connect audio / video
    pc.addEventListener('track', function(evt) {
        if (evt.track.kind == 'video') {
            document.getElementById('video').srcObject = evt.streams[0];
            // show play button after receiving video track
            document.getElementById('play').style.display = 'inline-block';
        }
    });

    document.getElementById('start').style.display = 'none';
    document.getElementById('stop').style.display = 'inline-block';
    negotiate();
}

function stop() {
    // reset play state
    isPlaying = false;

    document.getElementById('stop').style.display = 'none';
    document.getElementById('start').style.display = 'inline-block';
    document.getElementById('play').style.display = 'none';

    // clear video
    var video = document.getElementById('video');
    video.srcObject = null;
    video.load();

    // close data channel
    if (dataChannel) {
        dataChannel.close();
        dataChannel = null;
    }

    // clear message log
    document.getElementById('messageLog').innerHTML = '';

    // close peer connection
    setTimeout(function() {
        if (pc) {
            pc.close();
            pc = null;
        }
    }, 500);
}
