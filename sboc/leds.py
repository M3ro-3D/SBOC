"""Two independent 10-pixel SK6812 RGBW PWM channels on Pi 3B GPIO12/13."""
import threading

class LEDs:
    def __init__(self, enabled=True):
        self.lock=threading.RLock(); self.available=False; self.error=None
        self.pixels=[[(0,0,0,0)]*10 for _ in range(2)]
        if not enabled: self.error='Simulation mode'; return
        try:
            from rpi_ws281x import PixelStrip, SK6812_STRIP_GRBW
            self.strips=[PixelStrip(10,12,brightness=255,channel=0,strip_type=SK6812_STRIP_GRBW),
                         PixelStrip(10,13,brightness=255,channel=1,strip_type=SK6812_STRIP_GRBW)]
            for strip in self.strips: strip.begin()
            self.available=True
        except Exception as e: self.error=str(e)
    def show(self, pixels):
        with self.lock:
            self.pixels=[list(side) for side in pixels]
            if not self.available: return
            from rpi_ws281x import Color
            for strip, side in zip(self.strips,pixels):
                for i,(r,g,b,w) in enumerate(side): strip.setPixelColor(i,Color(r,g,b,w))
                strip.show()
    def off(self): self.show([[(0,0,0,0)]*10 for _ in range(2)])
