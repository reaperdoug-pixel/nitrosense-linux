> Thai guide from the upstream project ([napejoon/nitrosense-linux](https://github.com/napejoon/nitrosense-linux)).
> It describes the original Windows-style window. This fork replaced it with a dashboard and no
> longer needs the Windows package: see the main README, in Portuguese ([README.md](../README.md)),
> or its English version ([README.en.md](README.en.md)).

# คู่มือภาษาไทย

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
- กด**ปุ่ม NitroSense แล้วไม่มีอะไรเกิดขึ้น** → ดูหัวข้อ [NitroSense key](../README.md#a-tecla-nitrosense) (installer ตั้งค่าให้อัตโนมัติ: เปลี่ยน scancode `0xf5` เป็น `XF86Launch1` แล้วสร้าง shortcut ของ GNOME ไว้)
- **ตั้งไฟคีย์บอร์ดแล้วดูเหมือนไม่เปลี่ยน** → ไฟคีย์บอร์ดของโน้ตบุ๊กจะดับเองถ้าไม่ได้กดคีย์บอร์ด*ตัวเครื่อง*สักพัก (พิมพ์จากคีย์บอร์ดภายนอกไม่นับ) ให้กดปุ่มอะไรก็ได้บนคีย์บอร์ดโน้ตบุ๊กแล้วดูใหม่ หรือรัน `python3 -I tools/kbtest.py` เพื่อทดสอบทีละโหมด
- LCD Overdrive และ "ปิดไฟคีย์บอร์ดหลัง 30 วินาที" ไม่มีบน AN515-44 (จอ/BIOS ไม่รองรับ) โปรแกรมจึงซ่อนตัวเลือกนี้ไว้ เหมือนบน Windows
- ขึ้น *"permission denied"* → `echo ชื่อผู้ใช้ | sudo tee -a /etc/nitrosense/allowed-users`

### ถอนการติดตั้ง
```bash
sudo ./uninstall.sh
```
พัดลมจะกลับเป็น Auto และไฟล์ทั้งหมดของโปรแกรมจะถูกลบออก
