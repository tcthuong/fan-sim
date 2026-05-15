# Step-By-Step: Run Predict From Kit-CAE On Windows

Flow:

```text
Windows Kit-CAE UI -> Fan-Sim service on WSL/SSH -> /predict -> prediction.vtu/usda -> Kit-CAE import -> streamlines / CAE Flow
```

File này ưu tiên lệnh chạy từ Windows PowerShell. Không dùng PowerShell backtick line continuation cho các lệnh chính.

## 1. Template Case Là Gì

Service hiện tại load một graph template khi start:

```text
case_rpm_0060_pout_000
```

Template case không có nghĩa là chỉ predict RPM 60. Nó cung cấp mesh topology, cell centers, patch flags và graph structure. Khi kéo RPM slider trong Kit, service đổi feature RPM rồi predict trên template đó.

Nếu các case cùng geometry và cùng mesh, một template case là đủ.

## 2. PowerShell Window #1: Start Service Trong WSL

Mở Windows PowerShell tại bất kỳ folder nào và chạy một dòng này:

```powershell
wsl -d Ubuntu -- bash -lc "cd /mnt/d/nvidia/fan-sim && source .venv-ubuntu/bin/activate && fan-sim serve --config configs/fan_sim_colab.yaml --case-id case_rpm_0060_pout_000 --host 0.0.0.0 --port 8765"
```

Giữ cửa sổ này mở. Khi service sẵn sàng, terminal sẽ hiện Uvicorn hoặc ít nhất Windows sẽ gọi được `/health`.

Nếu thấy warning kiểu NVIDIA driver/CUDA quá cũ, đó chưa phải lỗi service. Nó chỉ báo PyTorch không dùng GPU và sẽ chạy CPU.

## 3. Nếu Service Chạy Trên Linux SSH Remote

Trên remote server, start service:

```bash
cd /root/fan-sim && source .venv/bin/activate && fan-sim serve --config configs/fan_sim_colab.yaml --case-id case_rpm_0060_pout_000 --host 127.0.0.1 --port 8765
```

Trên Windows PowerShell, mở tunnel:

```powershell
ssh -N -L 8765:127.0.0.1:8765 root@YOUR_SERVER_IP
```

Giữ cửa sổ tunnel này mở. Kit vẫn gọi service qua:

```text
http://127.0.0.1:8765
```

## 4. PowerShell Window #2: Test Service Health

Mở PowerShell mới và chạy:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8765/health
```

Expected:

```text
status
------
ok
```

Nếu health fail, đừng mở Kit. Quay lại Window #1 xem service đã chạy xong chưa hoặc đã crash chưa.

## 5. PowerShell Window #2: Test Predict API

Chạy một dòng này:

```powershell
$body = '{"case_id":"kit_test","rpm":1500,"outlet_pressure":0,"outputs":["vtu","usd","streamlines","particles"]}'; Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/predict -ContentType 'application/json' -Body $body
```

Expected response có các field:

```text
prediction_vtu
prediction_usd
fan_mesh_usd
fields
metrics
```

Output local sẽ nằm ở:

```text
D:\nvidia\fan-sim\runs\inference\kit_test_rpm1500\
```

Nếu service chạy trên remote Linux, output nằm trên remote server, không tự nằm trong `D:\nvidia\fan-sim`.

## 6. PowerShell Window #3: Launch Kit-CAE Với Fan-Sim Extension

Mở PowerShell mới và chạy một dòng:

```powershell
Set-Location D:\nvidia\kit-cae; .\repo.bat launch -n omni.cae_vtk.kit -- --ext-folder D:/nvidia/fan-sim/extensions --enable omni.fan_sim
```

Dùng `omni.cae_vtk.kit`, không dùng app basic, vì flow này cần VTK importer và CAE streamline support.

## 7. Predict Trong Kit UI

Scene mới có thể trống trong vài giây đầu. Extension tự gọi predict sau khi load với debounce khoảng 0.65 giây. Khi kéo RPM slider hoặc đổi Outlet Pa, extension cũng tự predict lại sau debounce nhẹ; nút `Predict RPM And Visualize` chỉ dùng khi muốn chạy ngay.

Trong cửa sổ `Fan-Sim`:

```text
Service:   http://127.0.0.1:8765
Case:      kit_test
RPM:       1500
Outlet Pa: 0
```

Lần test đầu:

```text
[x] Streamlines
[ ] CAE Flow
```

Nếu muốn chạy thủ công ngay, bấm:

```text
Predict RPM And Visualize
```

Sau khi service trả kết quả predict, extension xóa prim Fan-Sim cũ rồi import `prediction.vtu` trực tiếp vào `/World/CAE/FanSimPrediction`. Với Kit-CAE VTK delegate, không import VTU vào prim `Pending` rồi rename, vì rename dataset sau import có thể làm native CAE operator không fetch được `/Points`. Streamlines và CAE Flow được tạo sau khi dataset đã nằm ở path cuối cùng.

Pass khi status hiện tương tự:

```text
Loaded RPM 1500: /World/CAE/FanSimPrediction/...
```

Và Stage có:

```text
/World/CAE/FanSimPrediction
/World/CAE/FanSimFanMesh
/World/CAE/FanSimStreamlines
/World/CAE/FanSimStreamlineSeeds
```

Nếu service không trả được `fan_mesh.usda`, extension fallback sang:

```text
/World/CAE/FanSimSurface
```

`FanSimPrediction` là dataset CAE và thường không tự hiện trong viewport. Prim nhìn thấy được là `FanSimFanMesh`, `FanSimSurface`, `FanSimStreamlines`, hoặc `FanSimFlow`.

## 8. Test CAE Flow

Sau khi streamlines đã pass, bật:

```text
[x] CAE Flow
```

Bấm predict lại.

Pass khi Stage có thêm:

```text
/World/CAE/FanSimFlow
```

Extension dùng:

```text
U_pred              -> velocity field
velocity_magnitude  -> streamline color / flow scalar
```

Current Kit path uses native Kit-CAE operators:

```text
CreateCaeVizStreamlines        -> /World/CAE/FanSimStreamlines
CreateCaeVizFlowEnvironment    -> /World/CAE/FanSimFlow
CreateCaeVizFlowDataSetEmitter -> /World/CAE/FanSimFlow/DatasetInjector
```

Service vẫn có thể export `prediction_streamlines.usda` và `prediction_particles.usda` như artifact debug/offline, nhưng extension không reference chúng. Extension bind native CAE visual operators trực tiếp vào field trong `prediction.vtu`: `U_pred` cho velocity và `velocity_magnitude` cho color/scalar.

## 9. Check Output Files Trên Windows

Chạy:

```powershell
Get-ChildItem D:\nvidia\fan-sim\runs\inference\kit_test_rpm1500
```

Expected có:

```text
prediction.vtu
prediction.usda
fan_mesh.usda
streamline_seeds.json
particle_seeds.json
```

Optional debug/export artifacts có thể có thêm:

```text
prediction_streamlines.usda
prediction_particles.usda
```

## 10. Check Kit Log Khi Lỗi

Chạy:

```powershell
Select-String -Path D:\nvidia\kit-cae\logs\omni.cae_vtk.kit.log -Pattern "Fan-Sim|FanSim|Traceback|error"
```

Nếu Kit gọi được `/predict`, Window #1 hoặc remote service terminal phải có request log.

## 11. Common Failures

### Connection Refused

Service chưa chạy, chưa load xong, hoặc SSH tunnel chưa mở.

Verify:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8765/health
```

### Predictor Is Not Configured

Bạn đang chạy FastAPI không qua `fan-sim serve`, hoặc service không load predictor.

Start lại bằng lệnh Windows ở mục 2.

### PhysicsNeMo Checkpoint Not Found

Config đang trỏ sai model output. Kiểm tra file:

```powershell
Get-ChildItem D:\nvidia\fan-sim\artifacts\models\fan_mgn_colab_h100_quality
```

Folder đó phải có:

```text
checkpoint.pt
normalizer.json
```

### No Graph Template Found

Thiếu graph template:

```text
D:\nvidia\fan-sim\artifacts\graphs\case_rpm_0060_pout_000.graph.pt
```

Build lại trong WSL:

```powershell
wsl -d Ubuntu -- bash -lc "cd /mnt/d/nvidia/fan-sim && source .venv-ubuntu/bin/activate && fan-sim build-graphs --config configs/fan_sim_colab.yaml --jobs 1"
```

### Kit Mở Nhưng Không Thấy Streamlines

Kiểm tra Stage có prim `/World/CAE/FanSimStreamlines` chưa. Nếu có prim nhưng không thấy line, move camera vào vùng fan hoặc kiểm tra field target `U_pred`.

Streamline seed hiện được đặt như một đĩa upstream quanh fan:

```text
translation = (0.0, 0.0, 0.0)
scale       = (0.075, 0.075, 0.03)
max_steps   = 2200
```

Nếu muốn kéo streamline dài hơn nữa, chỉnh các giá trị trong `extensions/omni.fan_sim/omni/fan_sim/extension_config.py`, restart Kit rồi predict lại.

### RPM Thấp/Cao Nhìn Giống Nhau

Đây không nhất thiết là lỗi Kit. Base CFD hiện có inlet velocity:

```text
U = (0 0 -100)
```

Dòng nền này mạnh và giống nhau giữa các RPM, nên streamline toàn miền có thể rất giống. Pass/fail của Kit test là import/predict/streamline/flow prim hoạt động, không phải ảnh RPM phải khác rõ.

## 12. Minimal Pass Criteria

Một test Kit được coi là pass khi:

- `Invoke-RestMethod /health` trả `ok`.
- `Invoke-RestMethod /predict` trả path `prediction_vtu`.
- File `prediction.vtu` được tạo.
- Kit launch được với `--enable omni.fan_sim`.
- Bấm predict trong Fan-Sim UI không traceback.
- Stage có `/World/CAE/FanSimPrediction`.
- Stage có `/World/CAE/FanSimFanMesh` hoặc `/World/CAE/FanSimSurface`.
- Nếu bật Streamlines, Stage có `/World/CAE/FanSimStreamlines`.
- Nếu bật CAE Flow, Stage có `/World/CAE/FanSimFlow`.
