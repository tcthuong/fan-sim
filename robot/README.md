# Robot UR3e — URSim + Isaac Sim 6.0

Tất cả script liên quan đến robot UR3e nằm trong thư mục này.

---

## Cấu trúc

```
robot/
├── start-ursim.sh        — Khởi động URSim đầy đủ (PolyScope + URControl + VNC)
├── stop-ursim.sh         — Dừng tất cả
├── run-felix.sh          — Chạy PolyScope GUI đơn lẻ (debug)
├── control_ur3e.py       — Điều khiển robot qua RTDE (moveJ / moveL)
├── sync_ursim_isaac.py   — Đồng bộ URSim → Isaac Sim (headless)
├── isaac_gui_sync.py     — Đồng bộ URSim → Isaac Sim GUI (Script Editor)
└── isaac_debug.py        — Kiểm tra trạng thái trong Script Editor
```

---

## Cài đặt một lần

### 1. ur_rtde vào Python của Isaac Sim

```bash
cd /root/isaacsim
OMNI_KIT_ALLOW_ROOT=1 ./python.sh -m pip install ur_rtde
```

### 2. mutexshim32.so (đã có sẵn tại /root/mutexshim32.so)

File này là LD_PRELOAD shim cho URControl 32-bit chạy qua qemu-i386.
Không cần cài thêm gì.

---

## Sử dụng cơ bản

### Bước 1 — Khởi động URSim

```bash
bash /root/Downloads/fan-sim/robot/start-ursim.sh UR3
```

Tham số: `UR3` | `UR5` | `UR10` | `UR16` | `UR20`

VNC GUI: truy cập `http://<pod-ip>:6080` bằng trình duyệt.

Kiểm tra robot đang RUNNING:

```bash
printf "robotmode\n" | nc 127.0.0.1 29999
```

### Bước 2 — Điều khiển robot

```bash
python3 /root/Downloads/fan-sim/robot/control_ur3e.py
```

Chạy demo: HOME → PICK → PLACE → HOME.

### Bước 3 — Đồng bộ với Isaac Sim GUI

1. Mở Isaac Sim → **Window > Script Editor**
2. Mở file `isaac_gui_sync.py` hoặc copy nội dung vào Script Editor
3. Bấm **Run** — robot trong viewport sẽ đi theo URSim realtime

Để dừng:
```python
stop_sync()
```

---

## API RTDE nhanh

```python
import rtde_receive, rtde_control

rtde_r = rtde_receive.RTDEReceiveInterface("127.0.0.1")
rtde_c = rtde_control.RTDEControlInterface("127.0.0.1")

q   = rtde_r.getActualQ()           # joint angles (rad), 6 phần tử
tcp = rtde_r.getActualTCPPose()     # TCP pose [x, y, z, rx, ry, rz]

rtde_c.moveJ([0,-1.5707,0,-1.5707,0,0], speed=0.5, acceleration=0.5)
rtde_c.moveL(tcp, speed=0.1, acceleration=0.5)
rtde_c.stopJ(2.0)                   # dừng khẩn cấp
```

---

## Thông tin kỹ thuật

### Robot prim trong main.usda

```
/World/servo_indexed_belt_conveyor/Arm_Robot_02/ur3e_01
```

- USD asset: `restored/proj/assets/ur3e/ur3e/ur3e.usd`
- ArticulationRoot: `ur3e_01/root_joint`
- DOF order: `shoulder_pan(0)` → `shoulder_lift(1)` → `elbow(2)` → `wrist_1(3)` → `wrist_2(4)` → `wrist_3(5)`
- Khớp với thứ tự RTDE `getActualQ()` — không cần hoán đổi

### Tại sao cần set stiffness trước khi play?

Drive mặc định trong USD: `stiffness=41.25`, `maxForce=56 Nm` (quá yếu để snap nhanh).
`isaac_gui_sync.py` set `stiffness=1e8`, `maxForce=1e10` **trước** `timeline.play()` vì
PhysX đọc giá trị USD tại thời điểm khởi tạo — thay đổi sau khi play không có tác dụng.

### Kiến trúc URSim trên RunPod

| Vấn đề | Giải pháp |
|--------|-----------|
| Không có Docker daemon | udocker + image Ubuntu |
| URControl là binary 32-bit (i386) | Chạy qua `qemu-i386-static` |
| seccomp chặn syscall ABI i386 | qemu dịch syscall sang ABI 64-bit |
| `pthread_mutexattr_setprotocol` | LD_PRELOAD `/root/mutexshim32.so` |
| PolyScope cần Dashboard 29919 | Felix phải start TRƯỚC URControl |
| Java cần X display | `DISPLAY=:10.0`, `XAUTHORITY=/root/.Xauthority` |

### Ports

| Port | Dịch vụ |
|------|---------|
| 29999 | URSim Dashboard (TCP, text) |
| 30001 | Primary interface |
| 30002 | Secondary interface |
| 30003 | Realtime interface |
| 30004 | RTDE |
| 5900  | VNC (x11vnc) |
| 6080  | noVNC (browser) |

---

## Logs

```
/root/ursim-logs/polyscope.log   — PolyScope / felix
/root/ursim-logs/urcontrol.log   — URControl
/root/ursim-logs/x11vnc.log      — VNC
```
