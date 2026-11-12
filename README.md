# NitroSense for Linux

**Fan control, RGB keyboard lighting, power plans and hardware monitoring for Acer
Nitro laptops on Linux, with the look and behaviour of Acer NitroSense for Windows.**

NitroSense for Linux is a port of Acer **NitroSense 3.01.3056**, rebuilt from the
Windows application itself: the window uses the same layout, coordinates, colours,
images and vector icons. The background service sends the firmware the same WMI
commands, bit for bit, that the Windows service sends. Settings survive reboots,
suspend/resume and plugging or unplugging the charger, as they do on Windows.

> 🇹🇭 **ภาษาไทย**: ดูหัวข้อ [คู่มือภาษาไทย](#คู่มือภาษาไทย) ด้านล่าง

---

## Contents

- [Features](#features)
- [Supported hardware](#supported-hardware)
- [Requirements](#requirements)
- [Installation](#installation)
- [Using NitroSense](#using-nitrosense)
- [NitroSense key](#nitrosense-key)
- [How it works](#how-it-works)
- [Firmware interface reference](#firmware-interface-reference)
- [Files and configuration](#files-and-configuration)
- [Service API](#service-api)
- [Security model](#security-model)
- [Troubleshooting](#troubleshooting)
- [Uninstall](#uninstall)
- [Development](#development)
- [How this port was made](#how-this-port-was-made)
- [Limitations and differences from Windows](#limitations-and-differences-from-windows)
- [คู่มือภาษาไทย](#คู่มือภาษาไทย)
- [Disclaimer](#disclaimer)
- [License](#license)

---

## Features

### Fan Control
- **Auto**: the embedded controller (EC) manages the fans (factory behaviour).
- **Max**: both fans at full speed.
- **Custom**: separate sliders for the **CPU** and **GPU** fan, 0–100 % in 10 % steps,
  each with its own **Auto** switch (that fan stays automatic while the other is manual).
- **CoolBoost™**: raises the maximum fan speed in Auto mode. As on Windows, the switch
  only works in Auto mode and is greyed out in Max/Custom.
- Live **RPM** for both fans, with fans that spin faster as the RPM rises (same speed
  formula as NitroSense).

### Monitoring
- CPU and GPU **temperature** (red) and **load** (orange), refreshed every second.
- **Power in watts**: CPU package power from the Intel RAPL counters (read by the service,
  which runs as root: the counters are root-only) and GPU power from NVML (only while the dGPU
  is already awake). Shown on the Home tab and in the Monitoring header; the History tab charts
  both with the average, peak and an estimate of the energy used in the period. The service also
  records the iGPU and platform (psys) power for later use.
- **Throttling detection**: the service checks every 2 s whether the CPU is being held back,
  using kernel interfaces only: hardware thermal throttle counters, thermald/DPTF cooling
  devices, package power against its limits and the frequency cap. Home shows the state and the
  clock (e.g. "CPU 3,3 de 4,6 GHz") and the thermal protection point (Tjmax minus the TCC
  offset); a desktop alert appears after 10 s of continuous thermal throttling. The History
  tab charts the CPU frequency with the throttled periods shaded. The dGPU's clock and NVML
  slowdown reasons are shown while it is awake.
- **Processes tab**: the heaviest programs by CPU (share of the whole processor) and by
  memory (private resident pages, so shared libraries are not counted per process), grouped by
  program (a browser is one row). GPU users come from `nvidia-smi pmon`, run only while the dGPU
  is awake so monitoring never wakes it. A last card lists the programs holding `/dev/nvidia*`
  open, i.e. what keeps the dGPU from suspending; the service provides it because other users'
  file descriptors need root (`gpu_holders` command).
- **Fan curve** (Scenario tab, "Curva" mode): drag the points of a temperature/speed graph (or
  pick Quiet / Balanced / Performance); the service follows the hottest of the CPU and the
  awake GPU every 2 s and drives both fans in custom mode. Safety rules the curve cannot
  override: speeds never below 20 % and the curve must reach 100 % by 90 C; 100 % at 88 C (CPU) /
  82 C (GPU) whatever the curve says; speed rises at once but falls only after the lower target
  held for 8 s; if every temperature sensor fails the fans go back to the firmware's automatic
  mode; the fans are also handed back to automatic when the service stops.
- **Battery tab**: health (full-charge capacity against the original design, from
  `/sys/class/power_supply`), cycles, charge, power draw and time left (smoothed over the last
  minute), voltage and temperature when the firmware reports it, with plain-language advice.
  Charge and power history charts use the service's history; the health trend is logged every
  6 h. Only a critical battery problem raises a desktop alert. A switch limits charging to
  about 80 % (Acer's "battery health mode", read and set through the same WMI interface as the
  `acer-wmi-battery` driver); it appears only if the firmware reports it. `tools/probe_battery.py`
  is a read-only check for it.
- **History tab**: the service samples CPU/GPU/SSD temperature, fan speed and CPU load every
  30 s, even with the window closed, and keeps 30 days in `/var/lib/nitrosense/history/`.
  The tab shows 1 h to 30 d charts (average, peak, CPU load), min/avg/max, minutes spent
  above the attention limits, and the SSD wear trend (SMART counters logged every 6 h).
- **Alerts with the window closed**: `nitrosense-watch` starts with the desktop session and
  sends desktop notifications for high CPU/GPU temperature, a stopped fan and SSD health
  problems (new or worse alerts; critical ones repeat every 30 min). To disable it for one
  user, copy `/etc/xdg/autostart/nitrosense-watch.desktop` to `~/.config/autostart/` and add
  `Hidden=true`.
- 12-minute history charts (720 samples), with **Min/Max** over the visible history.
- Hover over a chart to see the time, temperature and load at that point.
- Temperatures in **°C or °F**.
- If the discrete GPU is powered down, the chart shows *"Discrete GPU is idle."* and
  monitoring does not wake it up.

### Power Plan
- Separate plans for **AC** and **Battery**: Power Saver, Balance, High-Performance.
- Switches automatically when the charger is plugged in or removed.
- Stays in sync with GNOME's power mode menu through power-profiles-daemon.

### Keyboard lighting (4-zone RGB)
- **Static**: one colour per zone, each zone on/off, brightness 1–5.
- **Dynamic**: Breathing, Wave, Zoom, Shifting and Neon, with speed 1–9, direction
  (left/right) for Wave and Shifting, and a colour choice where the firmware supports it.
- Colour picker with NitroSense's 9 basic colours, 9 recent colours and a full
  colour dialog (*More color…*).
- Animated keyboard preview.

### Settings (gear icon)
- **Sticky keys** (GNOME accessibility setting).
- **Windows and menu key** (Super/Menu key lock, done in firmware).
- **Temperature units** °C / °F.
- **LCD Overdrive** (panel response-time boost). Only shown when the panel supports it, as on
  Windows (where it depends on the factory flag `LCD_Overdrive_support`). The AN515-44's panel
  doesn't: the firmware accepts the command but the setting never takes effect.
- **Backlight off after 30 seconds** (keyboard backlight timeout). Only shown when the BIOS
  answers the request; the AN515-44 BIOS rejects it (`0xE2`).
- **Discrete GPU only**: appears only if the BIOS reports a GPU switch (not on AN515-44).

### NitroSense key
- The **NitroSense key** on the keyboard opens NitroSense, or brings it to the front if it is
  already open, as on Windows.

### Service
- Re-applies fan mode, CoolBoost, keyboard lighting, LCD Overdrive, the Win-key lock,
  the backlight timeout and power plans **at boot**, **after resume** and on **AC changes**.
- The GUI can be closed at any time; settings stay in effect.

---

## Supported hardware

| Status | Models |
|---|---|
| ✅ Tested | **Acer Nitro AN515-44** (Ryzen 4000 + GTX 1650 Ti, BIOS V1.04), Ubuntu 24.04, kernel 7.0 |
| 🟡 Should work (same NitroSense layout, `MachineType=1`), untested | AN515-43, AN515-45, AN515-51s, AN515-54, AN515-55, AN515-56, AN515-57, AN517-41, AN517-51, AN517-52, AN517-53, AN517-54, AN715-41, AN715-51, AN715-52, N9500-A, T9300 |
| ❌ Not supported (different NitroSense UI) | `MachineType=2` models with operation modes (AN515-46/47/58, AN517-42/43/55, Nitro ANX), and older `MachineType=0` models |

The installer reads `Plugs/<your model>/*.ini` from the NitroSense package, so per-model
settings (fan count, lighting type, default colours, colour calibration, visible options)
match what Windows uses for your laptop.

On an untested model, start with the read-only probe (`sudo python3 -I tools/probe.py`)
and check that the temperatures and RPM it prints look right. Then confirm the WMI
method numbers in your BIOS (see [Firmware interface reference](#firmware-interface-reference)).

---

## Requirements

- Acer Nitro laptop (see above), Ubuntu 24.04 or another Debian-based distribution with
  **GTK 4.10+**, Python 3.10+.
- The **NitroSense package for Windows** for your model, downloaded from Acer's support
  site (e.g. `Nitro Sense_Acer_3.01.3056_W10x64_A`). Unzip it anywhere.
- Installed automatically: `python3-gi`, `python3-gi-cairo`, `python3-cairo`,
  `gir1.2-gtk-4.0`, `acpi-call-dkms`.
- **Secure Boot**: `acpi_call` is an out-of-tree kernel module built by DKMS. With Secure
  Boot on, DKMS signs it with your Machine Owner Key (MOK). If you have never enrolled a
  MOK, Ubuntu asks you to set a password while installing and to enrol the key on the
  next reboot (blue *MOK management* screen → *Enroll MOK*).

---

## Installation

```bash
git clone https://github.com/napejoon/nitrosense-linux.git
cd nitrosense-linux
sudo ./install.sh "/path/to/Nitro Sense_Acer_3.01.3056_W10x64_A"
```

What the installer does:

1. Checks that the machine is an Acer and installs the dependencies.
2. Loads `acpi_call` and sets it to load at boot.
3. Runs a **read-only hardware probe** (only getter methods: temperatures, fan RPM,
   CoolBoost/Overdrive/backlight state). If the values look wrong, it stops and installs
   nothing else.
4. Copies the program to `/opt/nitrosense`.
5. Extracts the NitroSense artwork, fonts, icons and English strings from **your**
   package into `/usr/share/nitrosense/assets`. Nothing from the package is executed.
6. Copies your model's `Plugs/<model>/*.ini` to `/etc/nitrosense/model/`.
7. Lets the user who ran `sudo` talk to the service.
8. Installs the menu entry, the icon and the `nitrosense` command.
9. Sets up the **NitroSense key**: a udev hwdb rule remaps it to `XF86Launch1`, and a GNOME
   keyboard shortcut for your user opens NitroSense with it (see [NitroSense key](#nitrosense-key)).
10. Enables and starts the `nitrosensed` service.

Then open **NitroSense** from the application menu, or run:

```bash
nitrosense
```

To update to a newer version, `git pull` and run the installer again. Your settings in
`/var/lib/nitrosense` are kept.

---

## Using NitroSense

| Area | What to do |
|---|---|
| **Title bar** | Drag to move the window. Icons from right to left: close, minimise, settings (gear), keyboard lighting (keyboard icon). |
| **Fan Control** | Click **Auto**, **Max** or **Custom**. In Custom, drag or scroll a slider to set that fan's speed; the value is sent when you release it. **Auto** under a slider puts only that fan back on automatic. |
| **CoolBoost™** | Switch at the top right of the fan panel; the ⓘ icon explains it. Only active in Auto mode. |
| **Power Plan** | Pick the **AC** or **Battery** tab, then a plan. The plan for the current power source is applied immediately; the other one applies when you plug in or unplug. |
| **Monitoring** | Read-only. Hover over a chart for the values at that moment. |
| **Gear menu** | Switches for sticky keys, the Win key, °C/°F, LCD Overdrive and backlight timeout. Click outside or press Esc to close. |
| **Keyboard lighting** | Choose **Static** or **Dynamic** and set brightness with the slider at the top. Static: switch zones on/off and click a zone's colour square to pick a colour. Dynamic: choose an effect, speed, direction and colour. Every change goes to the keyboard immediately. Esc or ✕ closes the panel. |

Closing the window only closes the GUI. The service keeps the fans and lighting as you
left them.

---

## NitroSense key

The key with the NitroSense logo sends AT scancode
**0xf5**. Windows NitroSense's admin agent watches raw keyboard input for exactly this key
(`RAWKEYBOARD.MakeCode == 0x75`, i.e. 0xf5 without the release bit) and starts the app.

On Linux, systemd's keyboard database maps this scancode to `KEY_PRESENTATION` (keycode 425).
X11 cannot deliver keycodes above 247, so the desktop never sees the key. The installer
therefore:

1. adds `/etc/udev/hwdb.d/61-nitrosense.hwdb`, which remaps scancode `f5` to `prog1`
   (`XF86Launch1`) on Acer Nitro machines. systemd already does the same for the
   Predator "PredatorSense" button.
2. registers a GNOME custom shortcut *NitroSense*: `XF86Launch1` → `/opt/nitrosense/bin/nitrosense`.
   You can see or change it in *Settings → Keyboard → Custom Shortcuts*.

Other desktops (KDE, XFCE, …): bind the key `XF86Launch1` (shows as *Launch (1)*) to
`/opt/nitrosense/bin/nitrosense` in that desktop's shortcut settings. To check what any key
sends, run `sudo python3 -I tools/keyprobe.py 20` and press it.

Re-register the GNOME shortcut manually (as your user):
```bash
cd /opt/nitrosense && python3 -m nitrosense.shortcut install   # or: remove / status
```

---

## How it works

```
 Windows                                         Linux (this project)
 ───────                                         ────────────────────
 NitroSense.exe (WPF)                            nitrosense (GTK 4, your user)
        │ named pipe                                    │ Unix socket, JSON lines
        ▼ "PredatorSense_service_namedpipe"             ▼ /run/nitrosense/nitrosense.sock
 NitroSense service (root, native)               nitrosensed (root, Python)
        │ WMI: root\WMI                                 │ /proc/acpi/call  (acpi_call module)
        ▼ AcerGamingFunction / APGeAction               ▼
                 \_SB.PCI0.WMID.WMBH  /  \_SB.PCI0.WMID.WMAA   (ACPI, same methods)
                                        │
                                        ▼
                     Embedded controller / BIOS SMM (fans, RGB, panel)
```

- **`nitrosense/encoders.py`**: one pure function per NitroSense method. Each turns
  a setting into the exact 64-bit value Windows NitroSense sends (unit-tested against
  values taken from the decompiled IL).
- **`nitrosense/wmi.py`**: resolves the ACPI path from sysfs (`/sys/bus/wmi/devices/<GUID>`)
  and calls only the 12 allowed methods, each with a fixed input size.
- **`nitrosense/controller.py`**: call sequences. For example, static lighting is
  *backlight mode/brightness → 4 zone colours → zone on/off mask*, in that order, as
  `Popup_Lighting` does on Windows.
- **`nitrosense/daemon.py`**: the root service: socket server with per-connection
  `SO_PEERCRED` authorisation, persistent state, re-applying settings at startup, on
  logind `PrepareForSleep(false)` (resume) and on AC changes.
- **`nitrosense/power.py`**: power plans: CPU governor, CPU boost and power-profiles-daemon.
- **`nitrosense/sysmon.py`**: CPU load from `/proc/stat`, NVIDIA load/temperature
  through NVML. NVML is only opened while the GPU is already awake, and is released again
  on GPUs with runtime D3, so monitoring never stops the dGPU from sleeping.
- **`nitrosense/extract.py`, `geometry.py`**: read the `.appxbundle` → `Win32/NitroSense.exe`
  → .NET manifest resources → `.resources` → PNG/TTF/BAML. The BAML parser and WPF
  path-geometry decoder recover the icons as SVG paths.
- **`nitrosense/gui/`**: the window (`window.py`), controls that redraw the original WPF
  templates such as hexagon toggles, fan/power-plan buttons, sliders, tabs and charts
  (`controls.py`), the lighting panel (`lighting.py`) and the asset/icon renderer (`theme.py`).

### Power plan mapping

Windows switches Windows power schemes. Linux has none, so each plan maps to:

| Plan | CPU governor | CPU boost | power-profiles-daemon |
|---|---|---|---|
| Power Saver | `schedutil` | off | `power-saver` |
| Balance | `schedutil` | on | `balanced` |
| High-Performance | `performance` | on | `performance` (or `balanced` if your system has no performance profile) |

---

## Firmware interface reference

WMI class **AcerGamingFunction**, GUID `7A4DDFE7-5B5D-40B4-8595-4408E0CC7F56`, ACPI
`\_SB.PCI0.WMID.WMBH(instance, method, buffer)`:

| ID | Method | Used for | Input (little-endian) |
|---:|---|---|---|
| 1 | SetGamingProfile | Win key lock, LCD Overdrive | Win key: `0x02 \| on<<24`; Overdrive: `0x10 \| on<<48` |
| 3 | GetGamingProfile | read LCD Overdrive | `0` → state in byte 6 |
| 5 | GetGamingSysInfo | sensors | `0x01 \| index<<8`; index 1 CPU °C, 2 CPU RPM, 6 GPU RPM, 10 GPU °C → value in bytes 1–2 |
| 6 | SetGamingRgbKb | zone colour | `zone(1/2/4/8) \| R<<8 \| G<<16 \| B<<24` |
| 14 | SetGamingFanBehavior | fan mode | `0x9 \| cpu<<16 \| gpu<<22`, per fan 1=auto 2=max 3=custom (Auto `0x410009`, Max `0x820009`, Custom `0xC30009`) |
| 16 | SetGamingFanSpeed | custom speed | `fan(1=CPU, 4=GPU) \| percent<<8` |
| 20 | SetGamingKBBacklight | lighting effect | bytes: mode (0 static, 1 breathing, 2 neon, 3 wave, 4 shifting, 5 zoom), speed 1–9, brightness 0/25/50/75/100, 0x08 for wave, direction 1 right / 2 left, R, G, B |
| 22 / 23 | Set/GetGamingMiscSetting | GPU switch (if supported) | get `9` → 3 = supported; set `0x02 \| (1 dGPU-only / 2 hybrid)<<8` |
| 7 | GetGamingRgbKb | read zone colour | `zone(1/2/4/8)` → `[status, R, G, B]` |
| 21 | GetGamingKBBacklight | read lighting state | → `[status, mode, speed, brightness, 0x08, direction, R, G, B]` |

NitroSense switches zones on/off with `SetGamingLEDBehavior` (`0x08 | zone1<<40 | … | zone4<<43`).
On the AN515-44 BIOS this call answers status 2 (rejected), so NitroSense for Linux turns a zone
off by writing its colour as black through `SetGamingRgbKb`, which is verified in ACPI.

WMI class **APGeAction**, GUID `61EF69EA-865C-4BC3-A502-A0DEBA0CB531`, ACPI `\_SB.PCI0.WMID.WMAA`:

| ID | Method | Used for | Input |
|---:|---|---|---|
| 1 | SetFunction | CoolBoost / backlight timeout | CoolBoost `0x07 \| on<<16`; timeout `0x02 \| hotkey<<8 \| 0x80000 \| brightness<<32 \| (on ? 30<<40 : 0)` |
| 2 | GetFunction | read the same | CoolBoost `0x207`; backlight `0x01 \| hotkey<<8 \| 0x80000` |

Every output starts with a status byte (0 = success). The service treats any non-zero
status as an error and reports it in the GUI.

On the AN515-44 (BIOS V1.04), IDs 5, 6, 7, 16, 17, 20 and 21 are implemented in ACPI
(`SSDT5`) and were checked there directly. IDs 14, 22 and 23 match the mainline
`acer-wmi` driver. ID 1 (forwarded to the BIOS via SMI) is confirmed on hardware: the
Windows-key lock works through it. ID 3 answers Overdrive with `0xFF` in byte 6, which this
firmware uses for "not supported". If your BIOS differs, override the numbers in
`/etc/nitrosense/wmi.json`:

```json
{ "methods": { "SetGamingProfile": { "id": 1, "size": 8 } } }
```

Hardware test on AN515-44 (12/12 pass): zone colours and order, zone on/off, brightness 1–5,
Breathing, Wave in both directions, Neon, Shifting, Zoom and the Windows-key lock, plus fan
modes and sensors. `tools/kbtest.py` (no sudo) walks through every lighting mode and
the Windows-key lock through the running service and asks you to confirm what you see.

To inspect your own tables: `sudo bash tools/collect-acpi.sh` (read-only; writes the
dump to `tools/acpi-dump/`, which is git-ignored).

---

## Files and configuration

| Path | Purpose |
|---|---|
| `/opt/nitrosense/` | program (`bin/nitrosense`, `bin/nitrosensed`, `nitrosense/` package) |
| `/usr/local/bin/nitrosense` | GUI launcher |
| `/usr/share/nitrosense/assets/` | artwork extracted from your NitroSense package |
| `/etc/nitrosense/model/` | `Feature.ini`, `HW_Support.ini` of your model |
| `/etc/nitrosense/allowed-users` | users allowed to control the hardware (one per line) |
| `/etc/nitrosense/wmi.json` | optional WMI method-number overrides |
| `/var/lib/nitrosense/state.json` | saved settings (fan, lighting, power plans, …) |
| `~/.config/nitrosense/gui.json` | per-user GUI preferences (°C/°F, recent colours) |
| `/etc/systemd/system/nitrosensed.service` | service unit |
| `/etc/modules-load.d/nitrosense.conf` | loads `acpi_call` at boot |
| `/usr/share/applications/io.github.napejoon.NitroSense.desktop` | menu entry (app ID `io.github.napejoon.NitroSense`) |
| `/usr/share/icons/hicolor/<size>/apps/io.github.napejoon.NitroSense.png` | app icon: NitroSense's keycap tile from your package with the N lit red (fallback: the project's SVG in `scalable/apps`) |
| `/etc/udev/hwdb.d/61-nitrosense.hwdb` | NitroSense key → `XF86Launch1` |
| GNOME setting `custom-keybindings/nitrosense/` | shortcut: NitroSense key → open NitroSense |

To let another user control the hardware:

```bash
echo otheruser | sudo tee -a /etc/nitrosense/allowed-users
```

---

## Service API

The service listens on `/run/nitrosense/nitrosense.sock` and takes one JSON object per
line. You can script it, for example from Python:

```python
import sys; sys.path.insert(0, "/opt/nitrosense")
from nitrosense.client import Client
c = Client()
print(c.request("status")["sensors"])          # {'cpu_temp': 53, 'gpu_temp': 43, 'cpu_fan': 2097, 'gpu_fan': 2343}
c.request("set_fan", mode="max")
c.request("set_fan", mode="custom", cpu_percent=60, gpu_percent=40, cpu_auto=False, gpu_auto=False)
c.request("set_fan", mode="auto")
```

| Command | Arguments |
|---|---|
| `status` | none; returns sensors, saved state, firmware state, AC status |
| `set_fan` | `mode` auto/max/custom, optional `cpu_auto`, `gpu_auto`, `cpu_percent`, `gpu_percent` |
| `set_fan_speed` | `fan` cpu/gpu, `percent` 0–100 (Custom mode only) |
| `set_coolboost` | `on` |
| `set_keyboard` | `keyboard`: `mode` static/dynamic, `brightness` 1–5, `zones_on` [4 bools], `zone_colors` [4 × "#RRGGBB"], `effect` breathing/wave/zoom/shifting/neon, `speed` 1–9, `direction` 1/2, `effect_color` |
| `set_lcd_overdrive` / `set_win_key` / `set_backlight_timeout` | `on` |
| `set_power_plan` | `source` ac/battery, `plan` powersaver/balance/performance |
| `set_gpu_mode` | `discrete_only` (only if supported; takes effect after reboot) |

Replies are `{"ok": true, ...}` or `{"ok": false, "error": "..."}`.

---

## Security model

- Only the service runs as root. The GUI runs as your user.
- The service accepts connections only from root and the users listed in
  `/etc/nitrosense/allowed-users`, checked per connection with `SO_PEERCRED`.
- Requests are validated (types, ranges, `#RRGGBB` colours). The service builds the
  firmware input itself; clients never send raw WMI values.
- Only 12 known WMI methods can be called, each with a fixed input size. Unknown
  commands are rejected.
- `acpi_call` can call any ACPI method, but only root can use `/proc/acpi/call`.
- The systemd unit runs with `ProtectSystem=full`, `ProtectHome=true`,
  `PrivateTmp=true` and `NoNewPrivileges=true`.

---

## Troubleshooting

**"NitroSense service is not running"**
```bash
systemctl status nitrosensed
journalctl -u nitrosensed -b
sudo systemctl restart nitrosensed
```

**"Hardware interface unavailable: acpi_call kernel module is not loaded"**
```bash
sudo modprobe acpi_call
dkms status | grep acpi-call
mokutil --sb-state
```
With Secure Boot on, the module must be signed by an enrolled MOK. Run
`sudo dpkg-reconfigure acpi-call-dkms` and reboot; if the MOK enrolment screen
appears, choose *Enroll MOK*. After a **kernel update**, DKMS rebuilds the module
automatically.

**"permission denied"**: add your user to `/etc/nitrosense/allowed-users`
(see [Files and configuration](#files-and-configuration)).

**Black corners around the window**: the desktop needs compositing for the
transparent corners. Normal GNOME (X11 or Wayland) has it.

**High-Performance seems no different from Balance**: on some CPUs (e.g. Ryzen 4000
with `acpi-cpufreq`), power-profiles-daemon has no *performance* profile. NitroSense
still switches the governor to `performance`. Check with
`cat /sys/devices/system/cpu/cpufreq/policy0/scaling_governor`.

**Keyboard lighting doesn't seem to change**: the laptop keyboard switches its backlight off
after a while without keystrokes on *it* (typing on an external keyboard doesn't count).
Press any key on the laptop keyboard and look again. `python3 -I tools/kbtest.py` tests every
mode step by step.

**The NitroSense key does nothing**
```bash
systemd-hwdb query "evdev:atkbd:$(cat /sys/class/dmi/id/modalias)" | grep f5   # expect KEYBOARD_KEY_f5=prog1
cd /opt/nitrosense && python3 -m nitrosense.shortcut status                    # expect XF86Launch1 -> ...
```
If the first line shows `presentation`, run `sudo systemd-hwdb update && sudo udevadm trigger
--sysname-match="event*"`. If the shortcut is missing, run `python3 -m nitrosense.shortcut install`.

**Debug logging**
```bash
sudo systemctl edit nitrosensed     # add:  [Service]  Environment=NITROSENSE_LOG=DEBUG
sudo systemctl restart nitrosensed
journalctl -u nitrosensed -f        # shows every WMI call with its input/output
```

**Read-only check of the hardware path**
```bash
sudo python3 -I /path/to/nitrosense-linux/tools/probe.py
```

---

## Uninstall

```bash
sudo ./uninstall.sh
```

This puts the fans back on **Auto**, restores the Balance CPU policy, and removes the
service, the program, the artwork, the configuration and the saved state.
`acpi-call-dkms` stays installed; remove it with `sudo apt remove acpi-call-dkms`
if nothing else uses it.

---

## Development

```bash
# unit tests: encoders vs. values from the decompiled IL, daemon against simulated firmware
python3 -m unittest discover -s tests -v

# extract artwork somewhere local
python3 -m nitrosense.extract "/path/to/Nitro Sense_..._W10x64_A" /tmp/ns-assets

# run the GUI from the source tree against a simulated laptop (no root, no hardware)
python3 tests/fake_hw.py /tmp/ns.sock &
NITROSENSE_SOCKET=/tmp/ns.sock NITROSENSE_ASSETS=/tmp/ns-assets ./bin/nitrosense
```

Environment variables:

| Variable | Meaning |
|---|---|
| `NITROSENSE_SOCKET` | service socket the GUI connects to |
| `NITROSENSE_ASSETS` | artwork directory (default `/usr/share/nitrosense/assets`) |
| `NITROSENSE_MODEL_DIR` | model `.ini` directory (default `/etc/nitrosense/model`) |
| `NITROSENSE_LOG` | service log level (`DEBUG`, `INFO`, …) |

`tests/fake_hw.py` simulates the AN515-44 firmware (fan modes change the RPM,
temperatures drift), so every screen can be exercised without root.

---

## How this port was made

1. **Package**: the NitroSense installer contains an `.appxbundle`. Its x64 `.appx`
   holds `Win32/NitroSense.exe`, a .NET Framework 4.5 **WPF** application, and the MSI
   holds the native service (`PSSvc`) that talks to WMI.
2. **Code**: the IL of `NitroSense.exe` was read method by method (classes
   `CommonFunction`, `WMIFunction`, `Nitro_FanControlPage`, `Popup_Lighting`,
   `LightingDynamicUI`, `Nitro_MainWindow_Octavia`, …). This gave every bit field the app
   builds, the sensor indices, the slider ranges, the chart behaviour and which controls
   are shown for which effect and model year.
3. **Service**: strings in the service binary map each pipe command to a WMI method name
   on `AcerGamingFunction` or `APGeAction`.
4. **UI**: the compiled XAML (BAML) of the main window, fan page, monitoring page,
   popups and the style dictionary was decoded into element trees with exact sizes,
   margins, colours and control templates. WPF's binary path geometry was decoded into
   SVG paths, so the icons are the originals.
5. **Model selection**: `Startup` reads `Feature.ini` `MachineType`; type 1 (AN515-44)
   uses the *Octavia* main window and the classic monitoring/power-plan page.
6. **Firmware**: the laptop's ACPI tables were disassembled with `iasl` to confirm the
   method numbers, buffer sizes and sensor indices in `\_SB.PCI0.WMID.WMBH`.

---

## Limitations and differences from Windows

- **Not ported** (Windows-only software): Waves MaxxAudio / DTS sound modes, the
  NVIDIA GeForce Experience button, the Planet9 promotion.
- **Power plans** map to Linux CPU policy (see [Power plan mapping](#power-plan-mapping)),
  not to Windows power schemes.
- **Sticky keys** uses the GNOME setting and is hidden on desktops without it.
- **Fonts**: Segoe UI is a Windows font; the UI uses Open Sans / Noto Sans, which look
  very similar.
- **Keyboard preview** in the lighting panel is drawn by this app; it shows the 4 zones
  and an animated preview of the effect.
- **UI language**: English. NitroSense ships no Thai translation.
- **Zone on/off** is done by writing the zone black, because the AN515-44 BIOS rejects
  NitroSense's zone-mask call. The visible result is the same.
- **LCD Overdrive** and **backlight off after 30 seconds** are not available on the AN515-44
  and are hidden there.

---

## คู่มือภาษาไทย

### NitroSense for Linux คืออะไร
โปรแกรมควบคุมโน้ตบุ๊ก Acer Nitro บน Linux ที่ทำหน้าตาและการทำงานให้เหมือน NitroSense บน
Windows ทำโดยแกะจากตัวโปรแกรม Windows โดยตรง: layout ของหน้าต่าง ตำแหน่ง สี รูป และไอคอนเป็นของเดิม
และ service ส่งคำสั่งไปยัง firmware ด้วยค่าเดียวกับ Windows ทุกบิต

### ทำอะไรได้บ้าง
- **พัดลม**: Auto / Max / Custom (ปรับ CPU กับ GPU แยกกัน 0–100%) และ **CoolBoost™** (ใช้ได้เฉพาะโหมด Auto เหมือน Windows)
- **Monitoring**: อุณหภูมิและโหลดของ CPU/GPU, รอบพัดลม, กราฟย้อนหลัง 12 นาที, ค่า Min/Max, เลือก °C หรือ °F
- **Power Plan**: Power Saver / Balance / High-Performance ตั้งแยกกันตอนเสียบสายชาร์จและตอนใช้แบตเตอรี่ แล้วสลับให้อัตโนมัติ
- **ไฟคีย์บอร์ด RGB 4 โซน**: Static (สีแยกโซน เปิดปิดทีละโซน ความสว่าง 1–5) และ Dynamic (Breathing, Wave, Zoom, Shifting, Neon พร้อมความเร็ว ทิศทาง และสี)
- **ปุ่ม NitroSense บนคีย์บอร์ด**: กดแล้วเปิดโปรแกรมได้เหมือนบน Windows ถ้าเปิดอยู่แล้วจะดึงหน้าต่างขึ้นมาด้านหน้า
- **ตั้งค่าอื่นๆ**: Sticky keys, ล็อกปุ่ม Windows, LCD Overdrive, ปิดไฟคีย์บอร์ดเมื่อไม่ได้ใช้ 30 วินาที
- **จำค่าที่ตั้งไว้** แล้วตั้งกลับให้เองตอนเปิดเครื่อง ตอนตื่นจาก Sleep และตอนเสียบหรือถอดสายชาร์จ

### ติดตั้ง
1. โหลด **NitroSense สำหรับ Windows** ของรุ่นคุณจากเว็บ Acer แล้วแตกไฟล์ (เช่น `Nitro Sense_Acer_3.01.3056_W10x64_A`)
2. รันคำสั่งนี้:
   ```bash
   git clone https://github.com/napejoon/nitrosense-linux.git
   cd nitrosense-linux
   sudo ./install.sh "/path/to/Nitro Sense_Acer_3.01.3056_W10x64_A"
   ```
3. เปิด **NitroSense** จากเมนูแอป หรือพิมพ์ `nitrosense`

ก่อนติดตั้ง installer จะ**ตรวจฮาร์ดแวร์แบบอ่านอย่างเดียว**ก่อน ถ้าค่าที่อ่านได้ดูผิดปกติจะหยุดทันทีโดยไม่ติดตั้งอะไรเพิ่ม
ถ้าเปิด Secure Boot อยู่ module `acpi_call` ต้องเซ็นด้วย MOK ถ้ายังไม่เคย enroll Ubuntu จะให้ตั้งรหัส
แล้วให้กด *Enroll MOK* บนจอสีฟ้าตอนรีบูต

### วิธีใช้
- **ลากแถบด้านบน**เพื่อย้ายหน้าต่าง ไอคอนมุมขวาบนเรียงจากขวาไปซ้าย: ปิด, ย่อ, ตั้งค่า (เฟือง), ไฟคีย์บอร์ด
- **พัดลม**: กด Auto/Max/Custom ในโหมด Custom ให้ลากหรือ scroll แถบเลื่อน ค่าจะถูกส่งตอนปล่อยเมาส์ ปุ่ม Auto ใต้แถบจะให้พัดลมตัวนั้นกลับเป็นอัตโนมัติ
- **Power Plan**: เลือกแท็บ AC หรือ Battery แล้วเลือกแผน
- **ไฟคีย์บอร์ด**: กดไอคอนคีย์บอร์ด เลือก Static หรือ Dynamic แล้วปรับได้เลย คีย์บอร์ดเปลี่ยนตามทันที
- ปิดหน้าต่างได้ตามสบาย ค่าที่ตั้งไว้ยังทำงานต่อเพราะ service ดูแลอยู่

### แก้ปัญหาเบื้องต้น
- ขึ้น *"NitroSense service is not running"* → `sudo systemctl restart nitrosensed` แล้วดู log ด้วย `journalctl -u nitrosensed -b`
- ขึ้น *"acpi_call kernel module is not loaded"* → `sudo modprobe acpi_call` ถ้าไม่ผ่านให้เช็ก Secure Boot/MOK
- กด**ปุ่ม NitroSense แล้วไม่มีอะไรเกิดขึ้น** → ดูหัวข้อ [NitroSense key](#nitrosense-key) (installer ตั้งค่าให้อัตโนมัติ: เปลี่ยน scancode `0xf5` เป็น `XF86Launch1` แล้วสร้าง shortcut ของ GNOME ไว้)
- **ตั้งไฟคีย์บอร์ดแล้วดูเหมือนไม่เปลี่ยน** → ไฟคีย์บอร์ดของโน้ตบุ๊กจะดับเองถ้าไม่ได้กดคีย์บอร์ด*ตัวเครื่อง*สักพัก (พิมพ์จากคีย์บอร์ดภายนอกไม่นับ) ให้กดปุ่มอะไรก็ได้บนคีย์บอร์ดโน้ตบุ๊กแล้วดูใหม่ หรือรัน `python3 -I tools/kbtest.py` เพื่อทดสอบทีละโหมด
- LCD Overdrive และ "ปิดไฟคีย์บอร์ดหลัง 30 วินาที" ไม่มีบน AN515-44 (จอ/BIOS ไม่รองรับ) โปรแกรมจึงซ่อนตัวเลือกนี้ไว้ เหมือนบน Windows
- ขึ้น *"permission denied"* → `echo ชื่อผู้ใช้ | sudo tee -a /etc/nitrosense/allowed-users`

### ถอนการติดตั้ง
```bash
sudo ./uninstall.sh
```
พัดลมจะกลับเป็น Auto และไฟล์ทั้งหมดของโปรแกรมจะถูกลบออก

---

## Disclaimer

Unofficial project, not affiliated with or endorsed by Acer. "Acer", "Nitro",
"NitroSense" and "CoolBoost" are trademarks of Acer Inc. This repository contains
no Acer code, firmware or artwork; the installer reads the artwork from the
NitroSense package you downloaded yourself; that includes the app icon, which the
installer builds from NitroSense's own keycap tile (`nitrosense/iconmaker.py` lights the N red
like the backlit NitroSense key). The fallback icon `data/icons/io.github.napejoon.NitroSense.svg`
is original artwork made for this project. Changing fan and firmware settings is
at your own risk.

## License

MIT, see [LICENSE](LICENSE). The license covers this repository's code only; the
NitroSense artwork the installer extracts stays Acer's and is not redistributed.
