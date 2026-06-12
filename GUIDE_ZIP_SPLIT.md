# Hướng Dẫn Zip Split Có Password Trên Ubuntu

## 0. Lấy Branch `factory` Từ GitHub

### Clone lần đầu

```bash
git clone --branch factory https://github.com/tcthuong/fan-sim.git
cd fan-sim
```

### Nếu đã clone repo rồi

```bash
cd fan-sim
git fetch origin
git checkout factory
git pull origin factory
```

### Xác nhận đang ở đúng branch

```bash
git branch
```

Output phải hiện:

```text
* factory
```

---

Guide này dùng để nén folder `proj` thành nhiều file nhỏ, mỗi part tối đa `90M`, có mã hóa bằng password.

Password không được ghi vào guide, README, tên file, hoặc command trong tài liệu này. Nếu chữ tiếng Việt bị lỗi dấu trong editor hoặc terminal, hãy mở file này bằng encoding `UTF-8`.

## 1. Kiểm Tra Tool Cần Có

Chạy:

```bash
python3 --version
openssl version
split --version
```

Nếu thiếu tool, cài bằng:

```bash
sudo apt update
sudo apt install -y python3 openssl coreutils
```

## 2. Cấp Quyền Chạy Script

Chạy trong root project:

```bash
chmod +x scripts/zip_split.sh scripts/unzip_split.sh scripts/unzp.sh
```

## 3. Nén Folder `proj` Thành Các Part 90MB

Chạy:

```bash
bash scripts/zip_split.sh proj split_zip proj 90M
```

Script sẽ hỏi password 2 lần:

```text
Password:
Confirm password:
```

Nhập password trực tiếp trong terminal. Khi nhập, password sẽ không hiện lên màn hình. Không gửi password kèm các file nén.

Sau khi chạy xong, folder `split_zip` sẽ có dạng:

```text
proj.zip.enc.part-000
proj.zip.enc.part-001
proj.zip.enc.part-002
proj.README.txt
```

Chỉ gửi/copy các file sau cho người nhận:

```text
proj.zip.enc.part-*
proj.README.txt
```

Gửi password bằng kênh riêng, không đính kèm cùng archive.

## 4. Giải Nén Lại

Đặt tất cả file `proj.zip.enc.part-*` vào cùng một folder, ví dụ `split_zip`, rồi chạy:

```bash
bash scripts/unzp.sh split_zip restored proj
```

Script sẽ hỏi:

```text
Password:
```

Nếu password đúng, dữ liệu được phục hồi tại:

```text
restored/proj
```

## 5. Đổi Kích Thước Mỗi Part

Mặc định yêu cầu hiện tại là `90M`:

```bash
bash scripts/zip_split.sh proj split_zip proj 90M
```

Nếu muốn test nhanh với part nhỏ hơn:

```bash
bash scripts/zip_split.sh proj split_zip proj 10M
```

## 6. Chạy Test

Chạy:

```bash
bash tests/split_zip_test.sh
```

Kết quả đúng sẽ có:

```text
split zip test passed
interactive password test passed
```
