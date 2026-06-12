# Setup từ đầu — URSim + Isaac Sim 6 trên RunPod

Hướng dẫn này ghi lại **toàn bộ những gì đã cài** trên pod hiện tại,
theo đúng thứ tự thực hiện. Mục tiêu: có thể tái tạo lại môi trường
trên một pod sạch.

---

## Môi trường

| Thành phần | Phiên bản / chi tiết |
|------------|----------------------|
| RunPod GPU | RTX 3090 · 24 GB VRAM |
| OS | Ubuntu 22.04.5 LTS |
| NVIDIA Driver | 580.159.03 |
| CUDA Toolkit | 12.9 |
| Xorg | 1.21.1.4 (chạy tại `:10` qua xrdp) |
| Isaac Sim | 6.0.0-rc.59 tại `/root/isaacsim` |
| URSim | 5.25.2 (e-Series) trong udocker |
| ur_rtde | 1.6.3 |

---

## 1. System packages

```bash
apt-get update
apt-get install -y \
  qemu-user-static \      # qemu-i386-static cho URControl 32-bit
  x11vnc \                # expose Xorg :10 qua VNC
  netcat-openbsd \        # nc — dùng trong start-ursim.sh
  iproute2                # ss — kiểm tra ports
```

> RunPod đã có sẵn: `xrdp`, `xorgxrdp`, `Xorg`, `gcc`.
> Xorg :10 tự động chạy khi pod start (xrdp quản lý).

---

## 2. Isaac Sim 6.0

Isaac Sim được tải về dạng **standalone package** từ NVIDIA NGC
và extract ra `/root/isaacsim` (tổng ~26 GB).

```bash
# Tải từ NVIDIA (cần tài khoản NGC):
# https://catalog.ngc.nvidia.com/orgs/nvidia/teams/isaac/resources/isaac_sim
# -> Download -> isaac-sim-standalone-6.0.0-linux-x86_64.zip (hoặc tar.gz)

cd /root
unzip isaac-sim-standalone-6.0.0-linux-x86_64.zip
mv isaac-sim-standalone-6.0.0 isaacsim
```

Verify:

```bash
cat /root/isaacsim/VERSION
# -> 6.0.0-rc.59+release.41464.5f2772bc.gl
```

### Chạy GUI (cần Xorg :10)

```bash
DISPLAY=:10.0 XAUTHORITY=/root/.Xauthority \
  OMNI_KIT_ALLOW_ROOT=1 \
  /root/isaacsim/isaac-sim.sh
```

### Script Editor

Trong GUI: **Window → Script Editor** — dùng để chạy Python trong
context của Isaac Sim đang mở (không tạo instance mới).

---

## 3. ur_rtde

Cài vào **Python của Isaac Sim** (Python 3.12 riêng, không phải system Python):

```bash
cd /root/isaacsim
OMNI_KIT_ALLOW_ROOT=1 ./python.sh -m pip install ur_rtde
```

Verify:

```bash
OMNI_KIT_ALLOW_ROOT=1 ./python.sh -c "import rtde_receive; print('OK')"
```

> Nếu cần dùng với system Python (ví dụ `python3 control_ur3e.py`):
> ```bash
> pip3 install ur_rtde
> ```

---

## 4. URSim 5.25.2 qua udocker

RunPod không có Docker daemon → dùng **udocker** để giả lập container.

### 4a. Cài udocker (nếu chưa có)

```bash
pip3 install udocker
udocker install
```

### 4b. Load image URSim

Image URSim là custom build dựa trên Debian Bookworm, chứa:
- URSim 5.25.2 binaries tại `/ursim`
- JDK 1.8.0_371 (PolyScope/felix cần Java 8)
- noVNC 1.5.0 + websockify tại `/opt/novnc`
- Python 2.7 (URSim nội bộ)

```bash
# Nếu có file tar của image:
udocker load -i ursim-5.25.2.tar universalrobots

# Tạo container từ image:
udocker create --name=ursim universalrobots
# -> in ra container ID, ví dụ: b94e91f2-bfd0-3bb8-a65d-569a968f3137
```

> Container ID trên pod hiện tại: `b94e91f2-bfd0-3bb8-a65d-569a968f3137`
> Đường dẫn ROOT: `~/.udocker/containers/<ID>/ROOT`

### 4c. Symlinks cần thiết

`start-ursim.sh` tự tạo khi chạy, nhưng có thể tạo sẵn:

```bash
ROOT=~/.udocker/containers/b94e91f2-bfd0-3bb8-a65d-569a968f3137/ROOT
ln -sfn $ROOT/ursim /ursim
ln -sfn $ROOT/opt/urtool-3.0 /opt/urtool-3.0
mkdir -p /usr/local/urcontrol
ln -sfn $ROOT/usr/local/urcontrol/dynlibs /usr/local/urcontrol/dynlibs
```

---

## 5. mutexshim32.so

URControl (binary 32-bit i386) gọi các hàm `pthread_mutexattr_setprotocol`,
`pthread_mutexattr_setrobust`, v.v. — qemu-i386-static không hỗ trợ các
syscall priority-inheritance này và trả về `ENOTSUP`. Shim này stub tất cả
về `return 0`.

```bash
cat > /root/mutexshim.c << 'EOF'
/* Stub real-time pthread mutex/attr calls that qemu-i386 user-mode rejects (ENOTSUP=95) */
int pthread_mutexattr_setprotocol(void *a, int p) { return 0; }
int pthread_mutexattr_setrobust(void *a, int r) { return 0; }
int pthread_mutexattr_setprioceiling(void *a, int c) { return 0; }
int pthread_mutex_setprioceiling(void *m, int c, int *o) { return 0; }
int pthread_attr_setschedpolicy(void *a, int p) { return 0; }
int pthread_attr_setinheritsched(void *a, int i) { return 0; }
EOF

gcc -m32 -shared -fPIC -o /root/mutexshim32.so /root/mutexshim.c
```

> Yêu cầu gcc multilib:
> ```bash
> apt-get install -y gcc-multilib
> ```

---

## 6. noVNC

noVNC được **bundled sẵn trong URSim image** tại:
```
~/.udocker/containers/<ID>/ROOT/opt/novnc/
```

noVNC proxy (websockify) khởi động cùng với `start-ursim.sh` thông qua
script bên trong container. Trên pod hiện tại nó chạy độc lập:

```bash
# noVNC proxy (port 6080 -> VNC 5900)
NOVNC=~/.udocker/containers/b94e91f2-bfd0-3bb8-a65d-569a968f3137/ROOT/opt/novnc
nohup $NOVNC/utils/novnc_proxy --vnc localhost:5900 --listen 6080 &
```

x11vnc (phơi Xorg :10 ra port 5900) do `start-ursim.sh` khởi động.

---

## 7. Verify toàn bộ

```bash
# 1. Xorg :10 đang chạy?
ps aux | grep "Xorg :10"

# 2. Khởi động URSim
bash /root/Downloads/fan-sim/robot/start-ursim.sh UR3

# 3. Kiểm tra ports
ss -tlnp | grep -E "29999|30004|5900|6080"

# 4. RTDE connect
python3 -c "
import rtde_receive
r = rtde_receive.RTDEReceiveInterface('127.0.0.1')
print('connected:', r.isConnected())
import math
q = r.getActualQ()
print('joints (deg):', [round(math.degrees(x),1) for x in q])
"

# 5. RTDE control (robot phải RUNNING)
python3 /root/Downloads/fan-sim/robot/control_ur3e.py

# 6. GUI sync (trong Isaac Sim Script Editor)
# Copy nội dung isaac_gui_sync.py -> Run
```

---

## 8. Tại sao không dùng Docker?

RunPod container **chặn `CAP_SYS_ADMIN`** — Docker daemon trong container
cần quyền này để tạo namespaces. udocker không cần kernel namespaces, chỉ
cần `chroot`-like file extraction → hoạt động được.

URControl binary `i386` bị chặn thêm bởi seccomp rule của RunPod cho
ABI 32-bit. qemu-i386-static dịch syscall từ ABI i386 sang ABI x86_64,
qua được seccomp filter của host.

---

## 9. Thứ tự khởi động bắt buộc

```
PolyScope (felix) → port 29919 mở
        ↓
URControl connect → port 30004 mở
        ↓
power on + brake release → robot RUNNING
        ↓
RTDE / rtde_control khả dụng
```

Nếu đảo thứ tự (URControl trước felix): robot mãi DISCONNECTED vì
URControl không tìm thấy Dashboard server 29919 lúc khởi động.

---

## Cấu trúc file

```
fan-sim/robot/
├── SETUP.md              ← file này
├── README.md             ← hướng dẫn sử dụng hàng ngày
├── start-ursim.sh        ← khởi động URSim đầy đủ
├── stop-ursim.sh         ← dừng tất cả
├── run-felix.sh          ← chạy PolyScope đơn lẻ (debug)
├── control_ur3e.py       ← điều khiển robot moveJ / moveL
├── sync_ursim_isaac.py   ← đồng bộ URSim → Isaac Sim (headless)
├── isaac_gui_sync.py     ← đồng bộ URSim → Isaac Sim GUI (Script Editor)
└── isaac_debug.py        ← debug helper cho Script Editor
```
