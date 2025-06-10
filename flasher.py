import sys
import os
import io
import contextlib
from tkinter import *
from tkinter import ttk, messagebox
import serial.tools.list_ports
from threading import Thread
import requests
import esptool
import ctypes
import time
import json

# -----------------------------------------------------------------------------
# UI Theme Colors
# -----------------------------------------------------------------------------
BG  = "#2E3440"
FG  = "#D8DEE9"
ABG = "#4C566A"

# -----------------------------------------------------------------------------
# Dummy stream for frozen executables (--noconsole / DETACHED_PROCESS)
# -----------------------------------------------------------------------------
class _DummyIO(io.TextIOBase):
    def write(self, *args, **kwargs): return 0
    def flush(self): pass
    def writelines(self, lines): pass

if getattr(sys, "frozen", False):
    dummy = _DummyIO()
    for attr in ("stdout", "stderr", "__stdout__", "__stderr__"):
        if getattr(sys, attr) is None:
            setattr(sys, attr, dummy)



# -----------------------------------------------------------------------------
# Helpers (appdata_path, load_font)
# -----------------------------------------------------------------------------
def appdata_path(rel: str) -> str:
    base = os.environ.get("APPDATA", os.getcwd())
    path = os.path.join(base, "M5TallyClient")
    os.makedirs(path, exist_ok=True)
    return os.path.join(path, rel)

def load_font_windows(p: str):
    FR_PRIVATE = 0x10
    if os.path.exists(p): ctypes.windll.gdi32.AddFontResourceExW(p, FR_PRIVATE, 0)
load_font_windows(appdata_path("Assets/Fonts/Yu Gothic Light.ttf"))
load_font_windows(appdata_path("Assets/Fonts/EthnocentricRg-Regular 400.ttf"))

FONT  = "Yu Gothic Light"
FONT2 = "Yu Gothic Light"
FONT3 = "Ethnocentric Rg"

# -----------------------------------------------------------------------------
# Globals
# -----------------------------------------------------------------------------
run              = True
Compile_Progress = None
SaveFile_name    = "M5FlasherData.json"

base_url    = "http://tflash.it4all.ro:5000"
url         = f"{base_url}/compile"
status_url  = f"{base_url}/status/"
abort_url   = f"{base_url}/cancel/"
download_url= f"{base_url}/download/"

job_id          = None
Official_Status = "Waiting for server status..."

data = {"param1":"wifi","param2":"password","param3":"192.168.31.145","param4":"1"}
headers = {'Content-Type':'application/json'}

# -----------------------------------------------------------------------------
# Build UI frames (Welcome, Setup, Build)
# -----------------------------------------------------------------------------
win = Tk()
win.title("M5.Flasher")
H, W = win.winfo_screenheight(), win.winfo_screenwidth()
win.config(bg=BG)
win.geometry(f"{int(W/1.5)}x{int(H/1.4)}")
win.resizable(False,True)
win.update()

try:
    icon_path = appdata_path("Assets/flasher.ico")
    win.iconbitmap(default=icon_path)  # 'default' parameter ensures it appears in both window and taskbar
except Exception as e:
    print(f"Failed to set icon: {e}")  # Debug line
    pass

save_data = {
    "network": "",
    "password": "",
    "ip": "",
    "number": 0,
    "verion": 1
}


def save_json_to_appdata(data, filename=SaveFile_name):
    appdata = os.environ.get('APPDATA')
    if not appdata:
        raise RuntimeError("APPDATA environment variable not found.")
    if not os.path.exists(os.path.join(appdata, "M5TallyClient")):
        os.makedirs(os.path.join(appdata, "M5TallyClient"))
    filepath = appdata_path(filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    return filepath


def load_json_from_appdata(filename=SaveFile_name):
    appdata = os.environ.get('APPDATA')
    if not appdata:
        raise RuntimeError("APPDATA environment variable not found.")
    filepath = appdata_path(filename)
    if not os.path.exists(filepath):
        return {}  # Or return {} if you want an empty dict by default
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


if os.path.exists(appdata_path(SaveFile_name)):
    try:
        save_data = load_json_from_appdata(SaveFile_name)
    except:
        pass


def Toggle_Fullscreen(e=None):
    if win.attributes("-fullscreen"):
        win.attributes("-fullscreen", False)
        win.update()
    else:
        win.attributes("-fullscreen", True)
        win.update()


win.bind("<F11>", Toggle_Fullscreen)
win.bind("<Escape>", lambda x: [win.attributes("-fullscreen", False), win.update()])

def list_connected_usb_serial_devices():
    rv=[]
    for p in serial.tools.list_ports.comports():
        if p.vid and p.pid: rv.append({'name':p.description,'path':p.device})
    return rv


BIG = int(W / 30)
NORMAL = int(W / 50)
SMALL = int(W / 100)
side_pad = int(W / 8)

M5_path = ""
M5_network = ""
M5_password = ""
M5_number = ""
M5_ip = ""
Official_Status = "Waiting for Server Status..."
job_id = None


def Show_Welcome(e=None):
    global Welcome_Frame, M5_ip, M5_network, M5_number, M5_password, M5_path, job_id, Compile_Progress
    M5_path = ""
    M5_network = ""
    M5_password = ""
    M5_number = ""
    M5_ip = ""
    job_id = None
    Compile_Progress = None
    Welcome_Frame.pack(fill="both", expand=True)
    win.update()


def Show_Setup(e=None):
    global Setup_Frame, Setup_Id_Entry, Setup_IP_Entry, Setup_Network_Entry, Setup_Password_Entry, save_data
    Setup_Frame.pack(fill="both", expand=True)
    Setup_Id_Entry.delete(0, END)
    Setup_IP_Entry.delete(0, END)
    Setup_Network_Entry.delete(0, END)
    Setup_Password_Entry.delete(0, END)
    Setup_IP_Entry.insert(END, save_data['ip'])
    Setup_Network_Entry.insert(END, save_data['network'])
    Setup_Password_Entry.insert(END, save_data['password'])
    RemoveList()
    BuildList()
    win.update()


def SubmitData():
    global job_id, Build_Frame, save_data, Finish_Build_Button, Abort_Button, data, M5_number, M5_ip, M5_password, M5_network, Setup_Id_Entry, Setup_IP_Entry, Setup_Network_Entry, Setup_Password_Entry, Compile_Progress, M5_path, Status_Label, Job_Label, Official_Status
    error = ""
    try:
        M5_number = Setup_Id_Entry.get()
        if len(M5_number) > 0:
            M5_number = int(M5_number)
        else:
            raise ValueError("error")
    except:
        if error != "":
            error += "\n\n"
        error += " ● Missing M5 number.                                                    "
    try:
        M5_ip = Setup_IP_Entry.get()
        if len(M5_ip) < 5:
            raise ValueError("error")
    except:
        if error != "":
            error += "\n\n"
        error += " ● Missing Mixer IP.                                                    "
    try:
        M5_network = Setup_Network_Entry.get()
        if len(M5_network) < 1:
            raise ValueError("error")
    except:
        if error != "":
            error += "\n\n"
        error += " ● Missing Network name.                                                    "
    try:
        M5_password = Setup_Password_Entry.get()
        if len(M5_password) < 1:
            raise ValueError("error")
    except:
        if error != "":
            error += "\n\n"
        error += " ● Missing Network Password.                                                    "
    if M5_path == "":
        if error != "":
            error += "\n\n"
        error += " ● Missing Selected Device.                                                  "
    if error != "":
        messagebox.showerror("Missing Setup Data!", error)
    else:
        ClearScreen()
        save_data = {
            "network": str(M5_network),
            "password": str(M5_password),
            "ip": str(M5_ip),
            "number": int(M5_number),
            "version": 1
        }
        save_json_to_appdata(save_data, SaveFile_name)
        Show_Build()


def Show_Build():
    global job_id, Build_Frame, Finish_Build_Button, Build_Title, Abort_Button, data, M5_number, M5_ip, M5_password, M5_network, Setup_Id_Entry, Setup_IP_Entry, Setup_Network_Entry, Setup_Password_Entry, Compile_Progress, M5_path, Status_Label, Job_Label, Official_Status
    Build_Frame.pack(fill="both", expand=True)
    data['param1'] = f"{M5_network}"
    data["param2"] = f"{M5_password}"
    data["param3"] = f"{M5_ip}"
    data['param4'] = f"{M5_number}"
    Compile_Progress = "JOB ID"
    Official_Status = "Waiting for Server Status..."
    job_id = None
    Finish_Build_Button.config(state="disabled")
    Abort_Button.config(state="normal")
    Status_Label.config(text="Waiting for status...")
    Job_Label.config(text="Requesting Job ID...")
    Build_Title.config(text=" ° ° ° ° ° ")
    win.update()


def ClearScreen(e=None):
    global Welcome_Frame, Setup_Frame
    Welcome_Frame.pack_forget()
    Setup_Frame.pack_forget()
    Build_Frame.pack_forget()


def Close(e=None):
    global win, run, ServerCommunicationThread, Compile_Progress
    run = False
    win.withdraw()
    while ServerCommunicationThread.is_alive():
        pass
    if Compile_Progress != None and job_id != None:
        AbortCompilation()
    ServerCommunicationThread.join()
    win.destroy()


###############################################################
# WELCOME SCREEN ##############################################
###############################################################
###############################################################
###############################################################
###############################################################
Welcome_Frame = Frame(win, bg=BG)
Welcome_Title = Label(Welcome_Frame, text="M5.Flasher", bg=BG, fg=FG, font=(FONT3, BIG))
Welcome_Description = Text(Welcome_Frame, bg=BG, fg=FG, font=(FONT, SMALL), relief='flat', height=10, wrap=WORD)
Welcome_Title.pack(fill='x', pady=(20, 0))
Welcome_Description.pack(fill="x", padx=side_pad, pady=(20, 0))
Welcome_Description.insert(END,
                           """With M5.Flasher, pairing your Flash device with your Control console is quick and easy. Simply connect your device to your PC via USB, and let us handle the rest!\n\nTo continue setting up your M5 device, we only need a few details: the IP address of ATEM mixer, the network name (SSID), and its password. Additionally, please provide a device number so you can easily identify it later. Your information will never be shared with anyone. We respect and protect your privacy!""")
Welcome_Description.config(state="disabled")
Welcome_start_button = Button(Welcome_Frame, text="Start", bg=ABG, fg=FG, font=(FONT, NORMAL), relief='flat', border=0,
                              activeforeground=FG, activebackground=BG, command=lambda: [ClearScreen(), Show_Setup()])
Welcome_start_button.pack(fill='x', padx=side_pad, pady=(10, 0))
Welcome_quit_button = Button(Welcome_Frame, text="Quit", bg=ABG, fg=FG, font=(FONT, NORMAL), relief='flat', border=0,
                             activeforeground=FG, activebackground=BG, command=lambda: [Close()])
Welcome_quit_button.pack(fill='x', padx=side_pad, pady=(10, 0))

###############################################################
# SETUP SCREEN ################################################
###############################################################
###############################################################
###############################################################
###############################################################

Setup_Frame = Frame(win, bg=BG)
Setup_Title = Label(Setup_Frame, text="M5.Flasher Setup", bg=BG, fg=FG, font=(FONT3, NORMAL))
Setup_Title.pack(fill='x', pady=(20, 0))
Title_Spacer = Frame(Setup_Frame, height=5, bg=ABG)
Title_Spacer.pack(fill='x', expand=True)
Setup_MenuFrame = Frame(Setup_Frame, bg=BG)
Setup_MenuFrame.pack(fill='both', side='top', expand=True)

Setup_Top = Frame(Setup_MenuFrame, bg=BG)
Setup_Top.pack(fill='both', side='top', expand=True)
Spacer_0 = Frame(Setup_Top, width=int(W / 50), bg=BG)  # Adjust width as needed
Spacer_0.pack(fill='both', expand=True, side="left")
Setup_Left = Frame(Setup_Top, bg=ABG, border=5)
Setup_Left.pack(fill='both', side="left", expand=True)


def only_int(char):
    return char.isdigit() or char == ""


vcmd = win.register(only_int)

Network_Title_Section = Label(Setup_Left, text="Network", bg=ABG, fg=FG, font=(FONT, SMALL, "underline"), anchor="s",
                              pady=10)
Network_Title_Section.grid(row=0, column=0, columnspan=2)
Setup_Network_Label = Label(Setup_Left, text="• Name: ", bg=ABG, fg=FG, font=(FONT, SMALL), pady=10)
Setup_Network_Entry = Entry(Setup_Left, bg=BG, fg=FG, insertbackground=FG, relief='flat', font=(FONT2, SMALL))
Setup_Network_Label.grid(row=1, column=0, sticky="ew")
Setup_Network_Entry.grid(row=1, column=1)
Setup_Password_Label = Label(Setup_Left, text="• Password: ", bg=ABG, fg=FG, font=(FONT, SMALL), pady=10)
Setup_Password_Entry = Entry(Setup_Left, bg=BG, fg=FG, insertbackground=FG, relief='flat', font=(FONT2, SMALL),
                             show="•")
Setup_Password_Label.grid(row=2, column=0, sticky="ew")
Setup_Password_Entry.grid(row=2, column=1)
ATEM_Title_Section = Label(Setup_Left, text="ATEM Mixer", bg=ABG, fg=FG, font=(FONT, SMALL, "underline"), anchor="s",
                           pady=10)
ATEM_Title_Section.grid(row=3, column=0, columnspan=2)
Setup_IP_Label = Label(Setup_Left, text="• IP address: ", bg=ABG, fg=FG, font=(FONT, SMALL), pady=10)
Setup_IP_Entry = Entry(Setup_Left, bg=BG, fg=FG, insertbackground=FG, relief='flat', font=(FONT2, SMALL))
Setup_IP_Label.grid(row=4, column=0, sticky="ew")
Setup_IP_Entry.grid(row=4, column=1)
Setup_Id_Label = Label(Setup_Left, text="• Camera number: ", bg=ABG, fg=FG, font=(FONT, SMALL), pady=10)
Setup_Id_Entry = Entry(Setup_Left, bg=BG, fg=FG, validate="key", validatecommand=(vcmd, "%P"), insertbackground=FG,
                       relief='flat', font=(FONT2, SMALL))
Setup_Id_Label.grid(row=5, column=0, sticky="ew")
Setup_Id_Entry.grid(row=5, column=1)
Spacer = Frame(Setup_Top, width=int(W / 100), bg=BG)  # Adjust width as needed
Spacer.pack(fill='both', expand=True, side="left")
Setup_Right = Frame(Setup_Top, bg=BG)
Setup_Right.pack(fill='both', side="right", expand=True)
Tip_Text = Text(Setup_Right, bg=BG, fg=FG, font=(FONT, SMALL), relief='flat', height=3, wrap=WORD)
Tip_Text.pack(fill="x", padx=int(side_pad / 4), pady=(0, 10))
Tip_Text.insert(END,
                """Please connect your M5 device to this system using a USB cable if you haven’t done so already. Once connected, refresh the device list and select it from the list below!""")
Tip_Text.config(state="disabled")
Selected_Label = Label(Setup_Right, text="Selected Device: None", bg=BG, fg=FG, font=(FONT, SMALL), anchor='sw')
Selected_Label.pack(padx=int(side_pad / 4), pady=0, fill='x', expand=True)
Scrollable_Frame_Container = Frame(Setup_Right, bg=BG)
Scrollable_Frame_Container.pack(fill="both", expand=True, padx=int(side_pad / 4), pady=(0, 0))
canvas = Canvas(Scrollable_Frame_Container, bg=ABG, highlightthickness=0)
scrollbar = ttk.Scrollbar(Scrollable_Frame_Container, orient="vertical", command=canvas.yview)
scrollable_frame = Frame(canvas, bg=ABG)
scrollable_frame.bind(
    "<Configure>",
    lambda e: canvas.configure(
        scrollregion=canvas.bbox("all")
    )
)
canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
canvas.configure(yscrollcommand=scrollbar.set)
canvas.pack(fill="both", expand=True)


def _on_mousewheel(event):
    canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


canvas.bind_all("<MouseWheel>", _on_mousewheel)
canvas.pack(side="left", fill="both", expand=True)

USB_LIST = []
Devices = []


def RemoveList():
    global USB_LIST, Devices, M5_path, Selected_Label
    Devices = []
    for item in USB_LIST:
        item.pack_forget()
    M5_path = ""
    Selected_Label.config(text="Selected Device: None")


def SelectDevice(e=None):
    global USB_LIST, Selected_Label, M5_path, Devices
    if e != None:
        e = e.widget
        for w in USB_LIST:
            w.config(font=(FONT2, SMALL))
        e.config(font=(FONT2, SMALL, "underline"))
        for item in Devices:
            if item['name'] == e['text']:
                M5_path = item['path']
                show_path = item['path']
                if len(show_path) > 20:
                    show_path = show_path[:20] + "..."
                Selected_Label.config(text=f"Selected Device: {item['name']} • {show_path}")
    else:
        pass


def BuildList():
    global USB_LIST, Devices
    Devices = list_connected_usb_serial_devices()
    for i in Devices:
        new = Label(scrollable_frame, text=f"{i['name']}", bg=ABG, fg=FG, font=(FONT2, SMALL), padx=5, pady=2)
        new.pack(anchor="w")
        USB_LIST.append(new)
        new.bind("<Button-1>", SelectDevice)


RefreshButton = Button(Setup_Right, text="Refresh Devices", bg=ABG, fg=FG, font=(FONT, SMALL), relief='flat', border=0,
                       activeforeground=FG, activebackground=BG, command=lambda: [RemoveList(), BuildList()])
RefreshButton.pack(fill='x', expand=True, padx=int(side_pad / 4), pady=(5, 0))
Setup_Bottom = Frame(Setup_MenuFrame, bg=ABG)
Setup_Bottom.pack(fill='both', side='bottom', expand=True, pady=(5, 0))
cancel_setup = Button(Setup_Bottom, text="Cancel Setup", bg=BG, fg=FG, font=(FONT, SMALL), relief='flat', border=0,
                      activeforeground=FG, activebackground=BG, command=lambda: [ClearScreen(), Show_Welcome()])
cancel_setup.pack(fill='both', expand=True, padx=2, pady=4, side='left')
finish_setup = Button(Setup_Bottom, text="Finish Setup", bg=BG, fg=FG, font=(FONT, SMALL), relief='flat', border=0,
                      activeforeground=FG, activebackground=BG, command=lambda: [SubmitData()])
finish_setup.pack(fill='both', expand=True, padx=2, pady=4, side='right')

def sendCleanupRequest():
    try:
        response = requests.post(f"{abort_url}{job_id}", headers=headers, timeout=10)
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
    except Exception as e:
        print(f"Error sending cleanup request: {e}")

###############################################################
# Builind SCREEN ##############################################
###############################################################
###############################################################
###############################################################
###############################################################
def ServerCommunication():
    global Official_Status, Compile_Progress, job_id, M5_path, Abort_Button, Finish_Build_Button
    while run == True:
        if Compile_Progress == "JOB ID":
            # Step 1: Send the initial request to start compilation
            try:
                response = requests.post(url, json=data, headers=headers, timeout=10)  # Increased timeout
                response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
                # Assume the server returns a job ID to track the compilation
                response_data = response.json()
                job_id = response_data.get("job_id")
                if not job_id:
                    raise ValueError("error")
                else:
                    Compile_Progress = "WAIT"
            except Exception as e:
                Compile_Progress = None
                messagebox.showerror("Server error",
                                     "The server could not respond with a valid Job ID.\nPlease check your internet connection and try again!")
                ClearScreen()
                Show_Setup()
        if Compile_Progress == "WAIT":
            try:
                status_response = requests.get(f"{status_url}{job_id}", headers=headers, timeout=10)
                status_response.raise_for_status()
                status_data = status_response.json()

                if status_data.get("status") == "completed":
                    Official_Status = "Compilation completed. Downloading build..."
                    Compile_Progress = "DOWNLOAD"
                    Abort_Button.config(state="disabled")
                elif status_data.get("status") == "failed":
                    messagebox.showerror("Compilation failed!", f"{status_data.get('error')}")
                    Compile_Progress = None
                    Official_Status = "Waiting for Server Status..."
                    ClearScreen()
                    Show_Setup()
                else:
                    Official_Status = "Compilation in progress. Please Wait..."
                    time.sleep(10)  # Wait for 10 seconds before polling again
            except requests.exceptions.Timeout:
                Official_Status = "Status check timed out. Retrying..."
        if Compile_Progress == "DOWNLOAD":
            # Step 3: Download the compiled file
            try:
                file_response = requests.get(f"{download_url}{job_id}", headers=headers, timeout=180)
                file_response.raise_for_status()
                with open(appdata_path("sketch.bin"), 'wb') as f:
                    f.write(file_response.content)
                Official_Status = "Download completed. Flashing device..."
                Compile_Progress = "FLASH"
                Abort_Button.config(state="disabled")
            except Exception as e:
                Official_Status = f"Download failed with raised error: {e}. Download will be aborted!"
                Abort_Button.config(state="disabled")
                Finish_Build_Button.config(state="normal")
                Compile_Progress = "ERROR"
        if Compile_Progress == "FLASH":
            try:
                binp = appdata_path('sketch.bin')
                sys_argv = ["esptool", "--chip", "esp32s3", "--port", M5_path, "--baud", "460800", "write_flash", "-z",
                            "0x0", binp]
                sys.argv = sys_argv
                with contextlib.redirect_stdout(_DummyIO()), contextlib.redirect_stderr(_DummyIO()):
                    esptool.main()
                os.remove(binp)
                Compile_Progress = 'CLEAR';
                Official_Status = 'Done'
            except Exception as e:
                Official_Status = f"Flash failed: {e}";
                Compile_Progress = "ERROR"
        if Compile_Progress == "ERROR":
            try:
                sendCleanupRequest()
                Compile_Progress = None
                job_id = None
                Finish_Build_Button.config(state="normal")
            except Exception as e:
                Official_Status = f"Cleanup failed with raised error: {e}"
                Finish_Build_Button.config(state="normal")
        if Compile_Progress == "CLEAR":
            # Step 4: Cleanup after flashing
            try:
                sendCleanupRequest()
                Official_Status = "Cleanup completed. You can now disconnect your device."
                Compile_Progress = None
                job_id = None
                Finish_Build_Button.config(state="normal")
            except Exception as e:
                Official_Status = f"Cleanup failed with raised error: {e}"
                Finish_Build_Button.config(state="normal")


ServerCommunicationThread = Thread(target=ServerCommunication)
ServerCommunicationThread.start()


def GiveLoadingFeedback():
    global Build_Title, Job_Label, job_id, Status_Label, Official_Status
    if Compile_Progress != None and job_id != None:
        if Build_Title['text'] == " ° ° ° ° ° ":
            Build_Title.config(text=" • ° ° ° ° ")
        elif Build_Title['text'] == " • ° ° ° ° ":
            Build_Title.config(text=" • • ° ° ° ")
        elif Build_Title['text'] == " • • ° ° ° ":
            Build_Title.config(text=" • • • ° ° ")
        elif Build_Title['text'] == " • • • ° ° ":
            Build_Title.config(text=" • • • • ° ")
        elif Build_Title['text'] == " • • • • ° ":
            Build_Title.config(text=" • • • • • ")
        elif Build_Title['text'] == " • • • • • ":
            Build_Title.config(text=" ° • • • • ")
        elif Build_Title['text'] == " ° • • • • ":
            Build_Title.config(text=" ° ° • • • ")
        elif Build_Title['text'] == " ° ° • • • ":
            Build_Title.config(text=" ° ° ° • • ")
        elif Build_Title['text'] == " ° ° ° • • ":
            Build_Title.config(text=" ° ° ° ° • ")
        elif Build_Title['text'] == " ° ° ° ° • ":
            Build_Title.config(text=" ° ° ° ° ° ")
    else:
        if Build_Title["text"] != " ° ° ° ° ° ":
            Build_Title.config(text=" ° ° ° ° ° ")

    if Status_Label['text'] != Official_Status:
        Status_Label.config(text=Official_Status)
    if job_id != None and job_id != "":
        Job_Label.config(text=f"Job ID: {job_id}")
    Build_Title.after(100, GiveLoadingFeedback)


Build_Frame = Frame(win, bg=BG)
Build_Title = Label(Build_Frame, text=" ° ° ° ° ° ", bg=BG, fg=FG, font=("Arial", BIG))
Build_Title.pack(fill='x', pady=(20, 0))
Build_Title.after(100, GiveLoadingFeedback)

Status_Frame = Frame(Build_Frame, bg=ABG)
Status_Frame.pack(fill='both', expand=True)

Job_Label = Label(Status_Frame, text="Requesting Job ID...", bg=BG, fg=FG, font=(FONT, int(SMALL / 1.5)))
Job_Label.pack(fill='both', expand=True, pady=(0, 0), side='top')
Status_Label = Label(Status_Frame, text="Waiting for status...", bg=BG, fg=FG, font=(FONT, SMALL))
Status_Label.pack(fill='both', expand=True, pady=(5, 0), side="top")
Info_Text = Text(Status_Frame, bg=BG, fg=FG, font=(FONT, SMALL), relief='flat', height=10, wrap=WORD,
                 padx=int(side_pad / 4))
Info_Text.pack(fill="x", pady=(5, 0))
Info_Text.insert(END,
                 """The information you have provided is currently being sent to a server for processing. You have been added to the build queue, and once your build is complete, the server will return the setup and we will install it for you on your device.\nPlease do not disconnect your device, close the app, or cancel the build. All of these actions will result in your build being canceled from the build queue, and the setup will not complete.\n\nIf you want to abort the compilation, click the "Abort Compilation" button in the menu at the bottom of the screen.""")
Info_Text.config(state="disabled")
Controlls_Frame = Frame(Build_Frame, bg=ABG)
Controlls_Frame.pack(fill="both", expand=True, pady=(5, 0))




def AbortCompilation():
    global Compile_Progress, Official_Status, abort_url, Abort_Button, Finish_Build_Button
    try:
        Compile_Progress = None
        response = requests.post(f"{abort_url}{job_id}", headers=headers, timeout=10)
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        # Assume the server returns a job ID to track the compilation\
        Official_Status = "The compilation was successfully aborted by the client!"
        Abort_Button.config(state="disabled")
        Finish_Build_Button.config(state="normal")
    except Exception as e:
        messagebox.showerror("Server error",
                             "The server could not abort your request.                                      \nPlease check your internet connection and try again!")
        ClearScreen()
        Show_Setup()


Abort_Button = Button(Controlls_Frame, text="Abort Compilation", bg=BG, fg=FG, font=(FONT, SMALL), relief='flat',
                      border=0, activeforeground=FG, activebackground=BG, command=lambda: [AbortCompilation()])
Abort_Button.pack(fill='both', expand=True, padx=2, pady=4, side='left')
Finish_Build_Button = Button(Controlls_Frame, text="Finish Compilation", bg=BG, fg=FG, font=(FONT, SMALL),
                             relief='flat', border=0, activeforeground=FG, activebackground=BG,
                             command=lambda: [ClearScreen(), Show_Welcome()])
Finish_Build_Button.pack(fill='both', expand=True, padx=2, pady=4, side='right')

Show_Welcome()
win.protocol("WM_DELETE_WINDOW", Close)
win.mainloop()
