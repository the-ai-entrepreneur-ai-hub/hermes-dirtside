"""Run the paired foreground device agent."""
from .config import DeviceConfig
from .loop import serve

if __name__ == "__main__":
    serve(DeviceConfig.load())
