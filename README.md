
# Windows Policy Description Reader

Ứng dụng được xây dựng bằng Python và Tkinter, dùng để đọc và hiển thị cấu trúc Group Policy của Windows thông qua các tệp ADMX/ADML.

## 1. Chức năng

- Đọc cấu trúc Group Policy từ các tệp ADMX/ADML.
- Hiển thị tên danh mục, tên chính sách và mô tả chính sách.
- Hỗ trợ hai ngôn ngữ hiển thị mô tả:
  - English: Hiển thị mô tả tiếng Anh gốc.
  - Tiếng Việt: Tra cứu bản dịch từ từ điển JSON.
- Nếu không tìm thấy bản dịch, sử dụng mô tả tiếng Anh gốc.
- Tra cứu bản dịch trực tiếp trên máy, không cần Internet khi chạy.

Ứng dụng chỉ đọc thông tin Group Policy.

## 2. Cấu trúc thư mục

```text
WindowsPolicyDescriptionReader/
│
├── data/
│   └── description_translations_vi.json
│
├── tests/
│
├── main.py
├── policy_reader.py
├── build.bat
├── run.bat
├── README.md
└── VERSION.txt
```

## 3. Chạy chương trình

### Yêu cầu

- Windows .
- Python 3.11 x64.
- Các thư viện Python mà mã nguồn dự án yêu cầu.

### Cách chạy

Nhấp đúp vào:

```text
run.bat
```

Hoặc mở Command Prompt tại thư mục dự án và chạy:

```bat
py -3.11 main.py
```

## 4. Từ điển dịch tiếng Việt

Tệp từ điển phải nằm tại:

```text
data\description_translations_vi.json
```

Cấu trúc JSON:

```json
{
  "schema_version": 1,
  "source_language": "en",
  "target_language": "vi",
  "translations": {
    "English description": {
      "original": "English description",
      "vi": "Bản dịch tiếng Việt"
    }
  }
}
```

Các bản dịch được lưu trong đối tượng `translations`.

Không đổi tên tệp hoặc di chuyển thư mục `data` nếu mã nguồn vẫn đang sử dụng đường dẫn mặc định.

## 5. Đóng gói thành EXE

Để tạo ứng dụng EXE:

1. Đảm bảo Python 3.11 đã được cài đặt.
2. Kiểm tra `main.py`, `policy_reader.py` và thư mục `data`.
3. Nhấp đúp `build.bat`.
4. Chờ quá trình đóng gói hoàn tất.

Sau khi thành công, chương trình nằm tại:

```text
dist\WindowsPolicyDescriptionReader\WindowsPolicyDescriptionReader.exe
```

Ứng dụng được đóng gói theo dạng PyInstaller .

Khi chuyển sang máy tính khác, cần sao chép toàn bộ thư mục:

```text
dist\WindowsPolicyDescriptionReader
```


## 6. Sử dụng offline

- Từ điển JSON được lưu cục bộ.
- Không cần Internet để tra cứu bản dịch khi chạy ứng dụng.
- Máy đích không cần cài Python nếu sử dụng bản EXE đã đóng gói đầy đủ.

Lưu ý: Quá trình build lần đầu có thể cần Internet để cài PyInstaller nếu máy chưa có sẵn.

## 7. Xử lý lỗi

### Không tìm thấy tệp JSON

Kiểm tra:

```text
data\description_translations_vi.json
```

Đảm bảo tên tệp và vị trí chính xác.

### Không hiển thị bản dịch tiếng Việt

Kiểm tra cấu trúc JSON, đặc biệt là đối tượng `translations` và khóa `vi`.

Nếu một mô tả chưa có bản dịch, ứng dụng sẽ sử dụng mô tả tiếng Anh gốc theo cơ chế dự phòng trong mã nguồn.

### Build thất bại

Kiểm tra Python 3.11, PyInstaller và các thư viện mà chương trình sử dụng.

### chạy trên máy khác

Hãy chuyển toàn bộ thư mục `dist\WindowsPolicyDescriptionReader`.
