try:
    import aiortc
    print("aiortc imported")
    import av
    print("av imported")
    from aiortc.contrib.media import MediaPlayer
    print("MediaPlayer imported")
except Exception as e:
    print(e)
