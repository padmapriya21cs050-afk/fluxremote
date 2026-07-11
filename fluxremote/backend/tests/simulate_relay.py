import asyncio
import json
import websockets

SERVER = "ws://127.0.0.1:8000"
DEVICE_ID = "test-device-123"

async def host_runner():
    uri = f"{SERVER}/ws/host/{DEVICE_ID}"
    print("Host connecting to", uri)
    async with websockets.connect(uri) as ws:
        print("Host connected")
        # send a small keepalive and then listen
        await ws.send("hello_from_host")
        try:
            async for msg in ws:
                print("Host received:", repr(msg))
        except Exception as e:
            print("Host runner exception", e)

async def host_control_runner():
    uri = f"{SERVER}/ws/control-host/{DEVICE_ID}"
    print("Host control connecting to", uri)
    async with websockets.connect(uri) as ws:
        print("Host control connected")
        try:
            async for msg in ws:
                print("Host control received:", repr(msg))
        except Exception as e:
            print("Host control exception", e)

async def viewer_control_runner():
    uri = f"{SERVER}/ws/control/{DEVICE_ID}"
    print("Viewer control connecting to", uri)
    async with websockets.connect(uri) as ws:
        print("Viewer control connected")
        # send a control message
        msg = json.dumps({"type":"mouse_move","payload":{"x":123,"y":456},"message_id":"m1"})
        print("Viewer control sending:", msg)
        await ws.send(msg)
        # wait for ack
        try:
            async for m in ws:
                print("Viewer control received:", repr(m))
        except Exception as e:
            print("Viewer control exception", e)

async def viewer_runner():
    uri = f"{SERVER}/ws/viewer/{DEVICE_ID}"
    print("Viewer connecting to", uri)
    async with websockets.connect(uri) as ws:
        print("Viewer connected")
        # listen for frames
        try:
            async for msg in ws:
                print("Viewer received:", repr(msg))
        except Exception as e:
            print("Viewer exception", e)

async def main():
    # Start host and control-host first
    await asyncio.sleep(1)
    tasks = [
        asyncio.create_task(host_runner()),
        asyncio.create_task(host_control_runner()),
    ]
    # give server time to register host
    await asyncio.sleep(1)
    # start viewers
    tasks += [
        asyncio.create_task(viewer_runner()),
        asyncio.create_task(viewer_control_runner()),
    ]

    await asyncio.sleep(5)
    # Let them run a bit
    await asyncio.sleep(10)

if __name__ == '__main__':
    asyncio.run(main())
