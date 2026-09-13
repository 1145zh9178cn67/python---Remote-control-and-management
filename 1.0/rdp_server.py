import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import socket
import threading
import json
import base64
import io
from PIL import Image, ImageTk
import os
import time


class RemoteServerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Python 远程管理控制台 (Server)")
        self.root.geometry("1000x700")

        self.server_socket = None
        self.client_socket = None
        self.is_connected = False
        self.listen_thread = None

        # 状态变量
        self.desktop_running = False
        self.current_dir = ""

        self.create_widgets()
        self.start_server_listener()

    def create_widgets(self):
        # 顶部连接栏
        top_frame = tk.Frame(self.root, padx=10, pady=5, bg="#f0f0f0")
        top_frame.pack(fill=tk.X)

        tk.Label(top_frame, text="监听端口:", bg="#f0f0f0").pack(side=tk.LEFT)
        self.port_var = tk.StringVar(value="9999")
        tk.Entry(top_frame, textvariable=self.port_var, width=10).pack(side=tk.LEFT, padx=5)

        self.status_lbl = tk.Label(top_frame, text="状态: 未启动", fg="red", bg="#f0f0f0")
        self.status_lbl.pack(side=tk.LEFT, padx=10)

        self.conn_btn = tk.Button(top_frame, text="启动服务", command=self.toggle_server, bg="#4CAF50", fg="white")
        self.conn_btn.pack(side=tk.RIGHT)

        # 主功能区域 (Tabbed)
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # --- Tab 1: 远程命令 ---
        cmd_frame = tk.Frame(notebook)
        notebook.add(cmd_frame, text="远程命令终端")

        self.cmd_log = scrolledtext.ScrolledText(cmd_frame, state=tk.DISABLED, font=("Consolas", 10))
        self.cmd_log.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        cmd_input_frame = tk.Frame(cmd_frame)
        cmd_input_frame.pack(fill=tk.X, padx=5, pady=5)
        tk.Label(cmd_input_frame, text="CMD>").pack(side=tk.LEFT)
        self.cmd_entry = tk.Entry(cmd_input_frame, font=("Consolas", 10))
        self.cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.cmd_entry.bind('<Return>', self.send_command_event)
        self.send_cmd_btn = tk.Button(cmd_input_frame, text="执行", command=self.send_command, state=tk.DISABLED)
        self.send_cmd_btn.pack(side=tk.LEFT)

        # --- Tab 2: 远程桌面 ---
        desktop_frame = tk.Frame(notebook)
        notebook.add(desktop_frame, text="远程桌面查看")

        desk_control_frame = tk.Frame(desktop_frame, pady=5)
        desk_control_frame.pack(fill=tk.X)
        self.start_desk_btn = tk.Button(desk_control_frame, text="开始查看", command=self.toggle_desktop,
                                        state=tk.DISABLED)
        self.start_desk_btn.pack(side=tk.LEFT, padx=10)
        tk.Label(desk_control_frame, text="提示: 画面刷新较慢，请耐心等候").pack(side=tk.LEFT)

        self.desktop_canvas = tk.Canvas(desktop_frame, bg="black")
        self.desktop_canvas.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # --- Tab 3: 文件管理 ---
        file_frame = tk.Frame(notebook)
        notebook.add(file_frame, text="远程文件管理")

        file_nav_frame = tk.Frame(file_frame, pady=5)
        file_nav_frame.pack(fill=tk.X)
        tk.Label(file_nav_frame, text="路径:").pack(side=tk.LEFT)
        self.path_var = tk.StringVar(value="/")
        self.path_entry = tk.Entry(file_nav_frame, textvariable=self.path_var, width=50)
        self.path_entry.pack(side=tk.LEFT, padx=5)
        self.refresh_btn = tk.Button(file_nav_frame, text="刷新/进入", command=self.request_file_list,
                                     state=tk.DISABLED)
        self.refresh_btn.pack(side=tk.LEFT)

        # 文件列表树
        tree_frame = tk.Frame(file_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        columns = ("name", "size", "type")
        self.file_tree = ttk.Treeview(tree_frame, columns=columns, show="headings")
        self.file_tree.heading("name", text="文件名")
        self.file_tree.heading("size", text="大小")
        self.file_tree.heading("type", text="类型")
        self.file_tree.column("name", width=300)
        self.file_tree.column("size", width=100)
        self.file_tree.column("type", width=100)

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.file_tree.yview)
        self.file_tree.configure(yscrollcommand=scrollbar.set)
        self.file_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.file_tree.bind("<Double-1>", self.on_file_double_click)

        download_btn = tk.Button(file_frame, text="下载选中文件", command=self.download_selected_file,
                                 state=tk.DISABLED)
        download_btn.pack(pady=5)
        self.download_btn_ref = download_btn

    def start_server_listener(self):
        """在后台线程启动 TCP 服务器"""

        def listen():
            try:
                port = int(self.port_var.get())
                self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.server_socket.bind(('0.0.0.0', port))
                self.server_socket.listen(1)
                self.root.after(0, lambda: self.status_lbl.config(text=f"状态: 监听中 (Port {port})", fg="orange"))

                while True:
                    try:
                        client, addr = self.server_socket.accept()
                        self.client_socket = client
                        self.is_connected = True
                        self.root.after(0, self.on_client_connected)

                        # 启动消息接收线程
                        recv_thread = threading.Thread(target=self.receive_loop, daemon=True)
                        recv_thread.start()
                        break
                    except Exception as e:
                        if not self.server_socket: break

            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("错误", f"服务器启动失败: {e}"))

        t = threading.Thread(target=listen, daemon=True)
        t.start()

    def toggle_server(self):
        if self.is_connected:
            # 断开连接
            if self.client_socket:
                self.client_socket.close()
            self.is_connected = False
            self.client_socket = None
            self.desktop_running = False
            self.update_ui_state(False)
        else:
            # 启动服务逻辑已在 start_server_listener 中处理，这里主要是重置 UI
            if self.server_socket:
                self.server_socket.close()
            self.start_server_listener()

    def on_client_connected(self):
        self.status_lbl.config(text="状态: 已连接", fg="green")
        self.conn_btn.config(text="断开连接", bg="#f44336")
        self.send_cmd_btn.config(state=tk.NORMAL)
        self.start_desk_btn.config(state=tk.NORMAL)
        self.refresh_btn.config(state=tk.NORMAL)
        self.download_btn_ref.config(state=tk.NORMAL)
        self.log_message("[+] 客户端已连接")

    def update_ui_state(self, connected):
        if not connected:
            self.status_lbl.config(text="状态: 未启动", fg="red")
            self.conn_btn.config(text="启动服务", bg="#4CAF50")
            self.send_cmd_btn.config(state=tk.DISABLED)
            self.start_desk_btn.config(state=tk.DISABLED)
            self.refresh_btn.config(state=tk.DISABLED)
            self.download_btn_ref.config(state=tk.DISABLED)
            if self.desktop_running:
                self.desktop_running = False
                self.start_desk_btn.config(text="开始查看")

    def receive_loop(self):
        """持续接收客户端数据"""
        buffer_size = 4096 * 10
        while self.is_connected:
            try:
                # 简单协议：先接收 4 字节长度头
                header = self.recv_exact(4)
                if not header: break
                length = int.from_bytes(header, 'big')

                data = self.recv_exact(length)
                if not data: break

                msg = json.loads(data.decode('utf-8'))
                msg_type = msg.get('type')

                if msg_type == 'cmd_result':
                    self.root.after(0, lambda res=msg['data']: self.log_message(res))

                elif msg_type == 'desktop_frame':
                    if self.desktop_running:
                        img_data = base64.b64decode(msg['data'])
                        self.root.after(0, lambda img=img_data: self.update_desktop_image(img))

                elif msg_type == 'file_list':
                    self.root.after(0, lambda files=msg['data'], path=msg['path']: self.update_file_list(files, path))

                elif msg_type == 'file_download':
                    self.handle_file_download_response(msg)

            except Exception as e:
                print(f"Receive error: {e}")
                break

        self.root.after(0, lambda: self.handle_disconnect())

    def recv_exact(self, num_bytes):
        if not self.client_socket: return None
        data = bytearray()
        while len(data) < num_bytes:
            try:
                packet = self.client_socket.recv(num_bytes - len(data))
                if not packet: return None
                data.extend(packet)
            except:
                return None
        return bytes(data)

    def send_json(self, data_dict):
        if not self.client_socket: return
        json_str = json.dumps(data_dict).encode('utf-8')
        header = len(json_str).to_bytes(4, 'big')
        try:
            self.client_socket.sendall(header + json_str)
        except:
            self.handle_disconnect()

    # --- 功能 1: 远程命令 ---
    def send_command_event(self, event):
        self.send_command()

    def send_command(self):
        cmd = self.cmd_entry.get().strip()
        if not cmd: return
        self.log_message(f">>> {cmd}")
        self.cmd_entry.delete(0, tk.END)
        self.send_json({'type': 'exec_cmd', 'data': cmd})

    def log_message(self, msg):
        self.cmd_log.config(state=tk.NORMAL)
        self.cmd_log.insert(tk.END, msg + "\n")
        self.cmd_log.see(tk.END)
        self.cmd_log.config(state=tk.DISABLED)

    # --- 功能 2: 远程桌面 ---
    def toggle_desktop(self):
        if self.desktop_running:
            self.desktop_running = False
            self.start_desk_btn.config(text="开始查看")
            self.send_json({'type': 'stop_desktop'})
        else:
            self.desktop_running = True
            self.start_desk_btn.config(text="停止查看")
            self.send_json({'type': 'start_desktop'})

    def update_desktop_image(self, img_bytes):
        try:
            image = Image.open(io.BytesIO(img_bytes))
            # 适配 Canvas 大小
            canvas_w = self.desktop_canvas.winfo_width()
            canvas_h = self.desktop_canvas.winfo_height()
            if canvas_w > 1 and canvas_h > 1:
                image.thumbnail((canvas_w, canvas_h))

            tk_img = ImageTk.PhotoImage(image)
            self.desktop_canvas.delete("all")
            self.desktop_canvas.create_image(0, 0, anchor=tk.NW, image=tk_img)
            self.desktop_canvas.image = tk_img  # 保持引用
        except Exception as e:
            print(f"Image render error: {e}")

    # --- 功能 3: 文件管理 ---
    def request_file_list(self, path=None):
        if path is None:
            path = self.path_var.get()
        self.send_json({'type': 'list_files', 'data': path})

    def update_file_list(self, files, path):
        self.path_var.set(path)
        for i in self.file_tree.get_children():
            self.file_tree.delete(i)

        for f in files:
            name = f['name']
            size = f['size']
            ftype = "目录" if f['is_dir'] else "文件"
            self.file_tree.insert("", tk.END, values=(name, size, ftype))

    def on_file_double_click(self, event):
        selected = self.file_tree.selection()
        if not selected: return
        item = self.file_tree.item(selected)
        name = item['values']
        ftype = item['values']

        current_path = self.path_var.get()
        if current_path.endswith('/') or current_path.endswith('\\'):
            new_path = current_path + name
        else:
            new_path = current_path + os.sep + name

        if ftype == "目录":
            self.request_file_list(new_path)
        else:
            # 如果是文件，可以选择下载或查看属性，这里默认不操作，需点击下载按钮
            pass

    def download_selected_file(self):
        selected = self.file_tree.selection()
        if not selected:
            messagebox.showwarning("提示", "请选择一个文件")
            return
        item = self.file_tree.item(selected)
        name = item['values']
        ftype = item['values']

        if ftype == "目录":
            messagebox.showwarning("提示", "不能下载目录")
            return

        current_path = self.path_var.get()
        if current_path.endswith('/') or current_path.endswith('\\'):
            file_path = current_path + name
        else:
            file_path = current_path + os.sep + name

        # 请求下载
        self.send_json({'type': 'download_file', 'data': file_path})
        messagebox.showinfo("提示", "开始下载，请稍候... (大文件可能较慢)")

    def handle_file_download_response(self, msg):
        file_path = msg['path']
        content_b64 = msg['data']

        # 弹出保存对话框
        save_name = os.path.basename(file_path)
        save_path = filedialog.asksaveasfilename(initialfile=save_name)
        if save_path:
            try:
                content = base64.b64decode(content_b64)
                with open(save_path, 'wb') as f:
                    f.write(content)
                messagebox.showinfo("成功", "文件下载完成")
            except Exception as e:
                messagebox.showerror("错误", f"保存失败: {e}")

    def handle_disconnect(self):
        self.is_connected = False
        self.desktop_running = False
        self.update_ui_state(False)
        self.log_message("[-] 连接断开")


if __name__ == "__main__":
    root = tk.Tk()
    app = RemoteServerGUI(root)
    root.protocol("WM_DELETE_WINDOW",
                  lambda: [app.server_socket.close() if app.server_socket else None, root.destroy()])
    root.mainloop()
