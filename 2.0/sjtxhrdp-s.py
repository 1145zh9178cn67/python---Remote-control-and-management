import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import socket
import threading
import json
import base64
import time
import os


class ControlServer:
    def __init__(self, root):
        self.root = root
        self.root.title("远程控制系统 - 控制端 (Server)")
        self.root.geometry("1000x700")

        self.server_socket = None
        self.client_socket = None
        self.is_listening = False
        self.is_client_connected = False
        self.screen_stream_active = False

        self.create_widgets()
        # 启动一个线程专门用于接受连接
        self.accept_thread = threading.Thread(target=self.accept_loop, daemon=True)
        self.accept_thread.start()

    def create_widgets(self):
        # 顶部状态栏
        top_frame = ttk.Frame(self.root, padding=10)
        top_frame.pack(fill="x")

        ttk.Label(top_frame, text="监听端口:").pack(side="left")
        self.port_var = tk.StringVar(value="9178")
        ttk.Entry(top_frame, textvariable=self.port_var, width=10).pack(side="left", padx=5)

        self.status_btn = ttk.Button(top_frame, text="启动监听", command=self.toggle_server)
        self.status_btn.pack(side="left", padx=10)

        self.conn_status = ttk.Label(top_frame, text="未启动", foreground="gray")
        self.conn_status.pack(side="right")

        # 选项卡
        tab_control = ttk.Notebook(self.root)
        tab_control.pack(expand=1, fill="both", padx=10, pady=5)

        # 1. 终端控制
        term_tab = ttk.Frame(tab_control)
        tab_control.add(term_tab, text="远程终端")
        self.create_terminal_tab(term_tab)

        # 2. 桌面监控
        desk_tab = ttk.Frame(tab_control)
        tab_control.add(desk_tab, text="桌面监控")
        self.create_desktop_tab(desk_tab)

        # 3. 文件管理
        file_tab = ttk.Frame(tab_control)
        tab_control.add(file_tab, text="文件管理")
        self.create_file_tab(file_tab)

        # 4. 系统操作
        sys_tab = ttk.Frame(tab_control)
        tab_control.add(sys_tab, text="系统操作")
        self.create_system_tab(sys_tab)

    def create_terminal_tab(self, parent):
        frame = ttk.Frame(parent, padding=10)
        frame.pack(fill="both", expand=True)

        self.term_output = scrolledtext.ScrolledText(frame, state="disabled", height=20, font=("Consolas", 10))
        self.term_output.pack(fill="both", expand=True, pady=5)

        input_frame = ttk.Frame(frame)
        input_frame.pack(fill="x")
        self.cmd_entry = ttk.Entry(input_frame)
        self.cmd_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.cmd_entry.bind('<Return>', lambda e: self.send_command("exec_cmd", self.cmd_entry.get()))
        ttk.Button(input_frame, text="发送", command=lambda: self.send_command("exec_cmd", self.cmd_entry.get())).pack(
            side="left")

    def create_desktop_tab(self, parent):
        frame = ttk.Frame(parent, padding=10)
        frame.pack(fill="both", expand=True)

        ctrl_frame = ttk.Frame(frame)
        ctrl_frame.pack(fill="x", pady=5)
        ttk.Label(ctrl_frame, text="画质 (10-100):").pack(side="left")
        self.quality_scale = ttk.Scale(ctrl_frame, from_=10, to=100, orient="horizontal", length=200)
        self.quality_scale.set(50)
        self.quality_scale.pack(side="left", padx=5)

        ttk.Label(ctrl_frame, text="FPS (1-10):").pack(side="left")
        self.fps_scale = ttk.Scale(ctrl_frame, from_=1, to=10, orient="horizontal", length=100)
        self.fps_scale.set(2)
        self.fps_scale.pack(side="left", padx=5)

        self.stream_btn = ttk.Button(ctrl_frame, text="开始监控", command=self.toggle_screen_stream, state="disabled")
        self.stream_btn.pack(side="left", padx=10)

        # 使用Label显示图片
        self.screen_label = ttk.Label(frame, background="#eee", text="等待视频流...", anchor="center")
        self.screen_label.pack(fill="both", expand=True)

    def create_file_tab(self, parent):
        frame = ttk.Frame(parent, padding=10)
        frame.pack(fill="both", expand=True)

        nav_frame = ttk.Frame(frame)
        nav_frame.pack(fill="x", pady=5)
        self.path_var = tk.StringVar(value=".")
        ttk.Entry(nav_frame, textvariable=self.path_var, width=50).pack(side="left", padx=5)
        ttk.Button(nav_frame, text="刷新目录",
                   command=lambda: self.send_command("list_files", self.path_var.get())).pack(side="left")

        columns = ("name", "size", "type")
        self.file_tree = ttk.Treeview(frame, columns=columns, show="headings")
        self.file_tree.heading("name", text="名称")
        self.file_tree.heading("size", text="大小 (Bytes)")
        self.file_tree.heading("type", text="类型")
        self.file_tree.pack(fill="both", expand=True, pady=5)

        # 双击进入目录
        self.file_tree.bind("<Double-1>", self.on_file_double_click)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill="x")
        ttk.Button(btn_frame, text="下载选中", command=self.download_selected).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="上传文件", command=self.upload_file_dialog).pack(side="left", padx=5)

    def create_system_tab(self, parent):
        frame = ttk.Frame(parent, padding=10)
        frame.pack(fill="both", expand=True)

        ttk.Button(frame, text="弹出消息框 (Windows)", command=self.show_popup_dialog).pack(pady=10, fill="x")
        ttk.Button(frame, text="关机 (谨慎操作)", command=lambda: self.send_command("shutdown", "")).pack(pady=10,
                                                                                                          fill="x")

    def accept_loop(self):
        """后台线程：持续尝试绑定端口并接受连接"""
        while True:
            if self.is_listening and not self.is_client_connected:
                try:
                    # 如果socket没创建，先创建
                    if not self.server_socket:
                        port = int(self.port_var.get())
                        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                        self.server_socket.bind(('0.0.0.0', port))
                        self.server_socket.listen(5)
                        self.root.after(0, lambda: self.update_status("等待连接...", "orange"))

                    # 阻塞接受连接
                    client, addr = self.server_socket.accept()
                    self.client_socket = client
                    self.is_client_connected = True
                    self.root.after(0, self.on_client_connected)

                    # 启动接收数据线程
                    recv_thread = threading.Thread(target=self.receive_loop, daemon=True)
                    recv_thread.start()

                except Exception as e:
                    self.root.after(0, lambda: self.update_status(f"错误: {str(e)}", "red"))
                    self.is_listening = False
                    if self.server_socket:
                        self.server_socket.close()
                        self.server_socket = None
            time.sleep(0.5)

    def toggle_server(self):
        if self.is_listening:
            # 停止服务
            self.is_listening = False
            if self.server_socket:
                try:
                    self.server_socket.close()
                except:
                    pass
                self.server_socket = None
            self.status_btn.config(text="启动监听")
            self.update_status("已停止", "gray")
            self.stream_btn.config(state="disabled")
        else:
            # 启动服务
            self.is_listening = True
            self.status_btn.config(text="停止监听")
            # accept_loop 会处理具体的绑定

    def update_status(self, text, color):
        self.conn_status.config(text=text, foreground=color)

    def on_client_connected(self):
        self.update_status(f"已连接: {self.client_socket.getpeername()}", "green")
        self.append_term(">>> 客户端已连接\n")
        self.stream_btn.config(state="normal")

    def send_command(self, cmd_type, data):
        if not self.client_socket:
            messagebox.showwarning("警告", "没有客户端连接")
            return
        packet = {"type": cmd_type, "data": data}
        try:
            json_data = json.dumps(packet).encode('utf-8')
            # 发送长度头 (4字节)
            self.client_socket.sendall(len(json_data).to_bytes(4, 'big'))
            # 发送内容
            self.client_socket.sendall(json_data)
        except Exception as e:
            self.handle_disconnect()

    def handle_disconnect(self):
        self.is_client_connected = False
        self.client_socket = None
        self.update_status("连接断开", "red")
        self.append_term(">>> 客户端断开连接\n")
        self.stream_btn.config(state="disabled")
        if self.screen_stream_active:
            self.screen_stream_active = False
            self.stream_btn.config(text="开始监控")

    def receive_loop(self):
        """后台线程：接收客户端数据"""
        while self.is_client_connected:
            try:
                # 1. 读取长度头
                header = self.client_socket.recv(4)
                if not header:
                    break
                if len(header) < 4:
                    continue  # 简单处理，实际应更严谨

                length = int.from_bytes(header, 'big')

                # 2. 读取完整内容
                data = b""
                while len(data) < length:
                    chunk = self.client_socket.recv(length - len(data))
                    if not chunk:
                        break
                    data += chunk

                if not data:
                    break

                resp = json.loads(data.decode('utf-8'))
                self.root.after(0, lambda r=resp: self.handle_response(r))

            except Exception as e:
                break

        self.root.after(0, self.handle_disconnect)

    def handle_response(self, resp):
        r_type = resp.get("type")
        data = resp.get("data")

        if r_type == "cmd_output":
            self.append_term(data)
        elif r_type == "screen_data":
            if self.screen_stream_active:
                self.update_screen_image(data)
        elif r_type == "file_list":
            self.update_file_list(data)
        elif r_type == "file_content":
            self.save_downloaded_file(data)

    def append_term(self, text):
        self.term_output.config(state="normal")
        self.term_output.insert(tk.END, text)
        self.term_output.see(tk.END)
        self.term_output.config(state="disabled")

    def toggle_screen_stream(self):
        if not self.is_client_connected: return

        self.screen_stream_active = not self.screen_stream_active
        if self.screen_stream_active:
            self.stream_btn.config(text="停止监控")
            self.send_command("start_stream", {
                "quality": int(self.quality_scale.get()),
                "fps": int(self.fps_scale.get())
            })
        else:
            self.stream_btn.config(text="开始监控")
            self.send_command("stop_stream", None)
            self.screen_label.config(image='', text="监控已停止")

    def update_screen_image(self, b64_data):
        try:
            import base64
            import io
            from PIL import Image, ImageTk

            img_data = base64.b64decode(b64_data)
            image = Image.open(io.BytesIO(img_data))

            # 调整图片大小以适应标签
            label_width = self.screen_label.winfo_width()
            label_height = self.screen_label.winfo_height()
            if label_width > 1 and label_height > 1:
                image.thumbnail((label_width, label_height))

            photo = ImageTk.PhotoImage(image)
            self.screen_label.config(image=photo, text="")
            self.screen_label.image = photo  # 保持引用防止被GC
        except Exception as e:
            print(f"Image update error: {e}")

    def update_file_list(self, files):
        self.file_tree.delete(*self.file_tree.get_children())
        for f in files:
            self.file_tree.insert("", "end", values=(f['name'], f['size'], f['type']))

    def on_file_double_click(self, event):
        selected = self.file_tree.selection()
        if not selected: return
        item = self.file_tree.item(selected)
        name = item['values'][0]
        f_type = item['values'][2]

        if f_type == "DIR":
            current_path = self.path_var.get()
            if current_path.endswith("/") or current_path.endswith("\\"):
                new_path = current_path + name
            else:
                new_path = current_path + os.sep + name
            self.path_var.set(new_path)
            self.send_command("list_files", new_path)

    def download_selected(self):
        selected = self.file_tree.selection()
        if not selected: return
        item = self.file_tree.item(selected)
        name = item['values'][0]
        f_type = item['values'][2]

        if f_type == "DIR":
            messagebox.showinfo("提示", "暂不支持直接下载文件夹")
            return

        self.send_command("download_file", name)

    def save_downloaded_file(self, data_dict):
        path = data_dict['path']
        content = base64.b64decode(data_dict['content'])
        save_path = filedialog.asksaveasfilename(initialfile=os.path.basename(path))
        if save_path:
            with open(save_path, 'wb') as f:
                f.write(content)
            messagebox.showinfo("成功", "文件已下载")

    def upload_file_dialog(self):
        path = filedialog.askopenfilename()
        if not path: return
        try:
            with open(path, 'rb') as f:
                content = base64.b64encode(f.read()).decode('utf-8')
            self.send_command("upload_file", {
                "name": os.path.basename(path),
                "content": content,
                "target_dir": self.path_var.get()
            })
        except Exception as e:
            messagebox.showerror("错误", f"读取文件失败: {e}")

    def show_popup_dialog(self):
        msg = "Hello from Server Admin"
        self.send_command("popup", msg)


if __name__ == "__main__":
    root = tk.Tk()
    app = ControlServer(root)
    root.mainloop()
