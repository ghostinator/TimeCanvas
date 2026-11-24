# Camera capability report (2026-11-19, measured in VM 102 through USB passthrough)

- Device: USB `05a3:9422` ("ARC International Camera" in lsusb; V4L2 card "H264 USB Camera: USB Camera"; by-id prefix `usb-Sonix_Technology_Co.__Ltd._H264_USB_Camera_SN0001`). USB 2.0, 480M, driver uvcvideo.
- Nodes: `/dev/video0` = **MJPG + YUYV capture** (use this), `/dev/video2` = H.264 capture, `/dev/video1`, `/dev/video3` = metadata (not images).
- Stable path: `/dev/v4l/by-id/usb-Sonix_Technology_Co.__Ltd._H264_USB_Camera_SN0001-video-index0` (serial SN0001 is generic; revisit if a second camera is ever added; udev rule to follow if needed).
- Advertised MJPG modes: 1920x1080, 1280x720, 800x600, 640x480, 640x360, 352x288, 320x240, each at 30/25/15 fps. YUYV only up to 640x480.

## Measured stability (60-120 frame runs, via passthrough)
| Mode | Result | Avg JPEG |
|---|---|---|
| 1920x1080 @30 / @25 | fails to stream | - |
| 1920x1080 @15 | unstable: <20% of frames delivered, `Failed to resubmit video URB` in dmesg | ~140-190 KB |
| 1280x720 @30 / @25 | unstable (about 20% of frames delivered) | ~105-135 KB |
| **1280x720 @15** | **stable: 14.94 fps, 59/60 frames** | **~184 KB (max 353 KB)** |
| 640x480 @30 | stable: 32.3 fps | ~94 KB |

**Chosen mode: MJPG 1920x1080 @ 30 fps.** 1080p may work natively on the host (passthrough via QEMU xHCI is a suspect); not tested because it would require opening the camera on the host.

## Controls (video0)
brightness, contrast, saturation, hue, gain, sharpness, backlight_compensation, white_balance_automatic (on), white_balance_temperature (2800-6500, inactive while auto), auto_exposure (3=aperture priority, on), exposure_time_absolute (1-5000, inactive while auto), exposure_dynamic_framerate, power_line_frequency (**currently 50 Hz; US mains is 60 Hz -> camera-init should set 2 to avoid flicker**). Gamma read fails (-71). No focus/zoom/pan/tilt controls.
dmesg also shows a harmless `GET_INFO UVC control 2` error at attach.

## Capacity (avg JPEG 184 KB x captures/day x days x 1.20)
| Retention | 30 s interval | 60 s interval |
|---|---|---|
| per day (raw) | 529 MB | 265 MB |
| 30 days | 19 GB | 9.5 GB |
| 60 days | 38 GB | 19 GB |
| 90 days | 57 GB | 29 GB |
| 365 days | 232 GB | 116 GB |

Media disk is 256 GiB (~275 GB). 365 days at 30 s (232 GB, ~84%) would cross the 80% warning line and leave little room for videos; 30-90 days at 30 s fits comfortably. Defaults (30-day frames) use about 7% of the disk. Rendered videos are extra.

## Update 2026-11-19 (after fixing a bad USB hub/cabling)
The earlier 1080p/30 instability was caused by marginal cabling, not by the camera or the passthrough. Re-measured with `tests/live/modeprobe.py` (10 s per mode, ustreamer stopped):

| Mode | Frames delivered | Avg JPEG | USB errors |
|---|---|---|---|
| **1920x1080 @30** | 300/300 | 161 KB | 0 |
| 1920x1080 @25 | 251/250 | 194 KB | 0 |
| 1920x1080 @15 | 150/150 | 314 KB | 0 |
| 1280x720 @30 | 304/300 | 159 KB | 5 |
| 1280x720 @25 | 250/250 | 187 KB | 0 |
| 1280x720 @15 | 151/150 | 271 KB | 0 |

**Mode now in use: MJPEG 1920x1080 @ 30 fps** (note: the camera compresses harder at 30 fps; 1080p@15 gives ~2x larger, higher-quality stills if snapshot quality matters more than live smoothness). Capacity at 161 KB/frame is slightly below the table above. Older 720p frames stay in the archive; a render spanning mixed sizes scales everything to the first frame's size with padding.

## Update 2026-11-22: cabling lesson and the long outage
- Passive USB extensions with a hub in the middle failed repeatedly (USB -71 errors, offline loops). The camera dropped at 06:10 on 2026-11-21 and stayed offline about 28 hours, until the cabling was replaced on 2026-11-22.
- An **active 32 ft USB repeater** (Amazon Basics) replaced the extensions and hub and "works so much better" (owner-reported). Use active cabling for long runs.
- The outage went unnoticed because only the transition was logged; the alerts system (see ALERTS) now reports an offline camera within minutes and keeps reminding while it lasts.
