# Claude Code Vietnamese IME Fix

Fix lỗi gõ tiếng Việt trong Claude Code CLI với các bộ gõ OpenKey, EVKey, PHTV, Unikey... Hỗ trợ **native installer** (macOS/Linux) và npm (Windows).

**Author:** [datnt](https://github.com/ntd4996)

## Vấn đề

Khi gõ tiếng Việt trong Claude Code CLI, các bộ gõ sử dụng kỹ thuật "backspace rồi thay thế" để chuyển đổi ký tự (ví dụ: `a` → `á`). Claude Code xử lý phần backspace nhưng không chèn ký tự thay thế, dẫn đến:

- Ký tự bị "nuốt" hoặc mất khi gõ
- Văn bản hiển thị không đúng với những gì đã gõ
- Phải copy-paste từ nơi khác thay vì gõ trực tiếp

## Cài đặt

Lần đầu chạy sẽ **tự động fix** luôn.

**macOS / Linux:**

```bash
curl -fsSL https://raw.githubusercontent.com/ntd4996/claude-code-vietnamese-fix/main/install.sh | bash
```

**Windows (PowerShell):**

```powershell
irm https://raw.githubusercontent.com/ntd4996/claude-code-vietnamese-fix/main/install.ps1 | iex
```

## Sau khi update Claude Code

Chạy lại fix:

```bash
python3 ~/.claude-vn-fix/patcher.py
```

**Windows:**

```powershell
python ~\.claude-vn-fix\patcher.py
```

## Các lệnh

```bash
python3 patcher.py              # Tự động phát hiện và fix
python3 patcher.py --restore    # Khôi phục từ backup
python3 patcher.py --path FILE  # Fix file cụ thể
python3 patcher.py --help       # Hiển thị hướng dẫn
```

## Cập nhật patcher

```bash
cd ~/.claude-vn-fix && git pull
```

## Credits

Tham khảo và cải tiến từ [PHTV](https://github.com/phamhungtien/PHTV).

---

<div align="center">

<img src="https://github-readme-stats.vercel.app/api?username=ntd4996&show_icons=true&theme=radical" alt="GitHub Stats" />

<br/><br/>

<h3>Support My Work | Ủng Hộ Tôi</h3>

<a href="https://www.buymeacoffee.com/ntd4996">
  <img src="https://img.buymeacoffee.com/button-api/?text=Buy me a coffee&emoji=&slug=datnt&button_colour=FF5F5F&font_colour=ffffff&font_family=Cookie&outline_colour=000000&coffee_colour=FFDD00" />
</a>

</div>

---

## Bản quyền

© 2026 [datnt.dev](https://datnt.dev) | [GitHub](https://github.com/ntd4996)

MIT License
