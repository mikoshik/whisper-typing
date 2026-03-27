import time
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL, CoInitialize, CoUninitialize
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

def test_mute():
    try:
        CoInitialize()
        print("Finding speakers...")
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        
        print("Muting...")
        volume.SetMute(1, None)
        print("Muted. Waiting 3 seconds...")
        time.sleep(3)
        
        print("Unmuting...")
        volume.SetMute(0, None)
        print("Unmuted.")
        CoUninitialize()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_mute()
