// FiveQThoughts – native Windows host (counterpart of native/macos_host.swift)
//
//  * Own app window with embedded WebView2 (Chromium/Edge) – own taskbar / Alt+Tab entry
//  * Tray icon (lightning bolt) with menu: show/hide, reload, autostart, quit
//  * Global hotkey Ctrl+Alt+Q toggles the window from any application
//  * Closing the window hides it to the tray (like ⌘W on macOS); "Quit" really exits
//  * Starts the Python backend (bundled FiveQThoughts-backend.exe or app.py) on a free port
//    unless --url is given (e.g. when launched by `python app.py`)
//  * Single instance: a second launch just brings the running window to the front
//
// Command line:  FiveQThoughts.exe [--url http://127.0.0.1:PORT] [--hidden]

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;
using Microsoft.Win32;

namespace FiveQThoughtsHost
{
    internal static class Native
    {
        public const int WM_HOTKEY = 0x0312;
        public const uint MOD_ALT = 0x0001;
        public const uint MOD_CONTROL = 0x0002;
        public const uint MOD_NOREPEAT = 0x4000;
        public const uint VK_N = 0x4E;
        public const uint VK_Q = 0x51;
        public static readonly IntPtr HWND_BROADCAST = new IntPtr(0xffff);

        [DllImport("user32.dll", SetLastError = true)]
        public static extern bool RegisterHotKey(IntPtr hWnd, int id, uint fsModifiers, uint vk);

        [DllImport("user32.dll")]
        public static extern bool UnregisterHotKey(IntPtr hWnd, int id);

        [DllImport("user32.dll")]
        public static extern bool SetForegroundWindow(IntPtr hWnd);

        [DllImport("user32.dll")]
        public static extern IntPtr GetForegroundWindow();

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        public static extern uint RegisterWindowMessage(string lpString);

        [DllImport("user32.dll")]
        public static extern bool PostMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);

        [DllImport("user32.dll")]
        public static extern bool AllowSetForegroundWindow(int dwProcessId);

        [DllImport("dwmapi.dll")]
        public static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int attrValue, int attrSize);

        // --- Job object: backend process dies together with the host, even on crash ---
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
        public static extern IntPtr CreateJobObject(IntPtr lpJobAttributes, string lpName);

        [DllImport("kernel32.dll")]
        public static extern bool SetInformationJobObject(IntPtr hJob, int infoClass, IntPtr lpInfo, uint cbInfoLength);

        [DllImport("kernel32.dll")]
        public static extern bool AssignProcessToJobObject(IntPtr hJob, IntPtr hProcess);

        [StructLayout(LayoutKind.Sequential)]
        public struct JOBOBJECT_BASIC_LIMIT_INFORMATION
        {
            public long PerProcessUserTimeLimit;
            public long PerJobUserTimeLimit;
            public uint LimitFlags;
            public UIntPtr MinimumWorkingSetSize;
            public UIntPtr MaximumWorkingSetSize;
            public uint ActiveProcessLimit;
            public UIntPtr Affinity;
            public uint PriorityClass;
            public uint SchedulingClass;
        }

        [StructLayout(LayoutKind.Sequential)]
        public struct IO_COUNTERS
        {
            public ulong ReadOperationCount, WriteOperationCount, OtherOperationCount;
            public ulong ReadTransferCount, WriteTransferCount, OtherTransferCount;
        }

        [StructLayout(LayoutKind.Sequential)]
        public struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        {
            public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
            public IO_COUNTERS IoInfo;
            public UIntPtr ProcessMemoryLimit;
            public UIntPtr JobMemoryLimit;
            public UIntPtr PeakProcessMemoryUsed;
            public UIntPtr PeakJobMemoryUsed;
        }

        public const int JobObjectExtendedLimitInformation = 9;
        public const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000;

        public static IntPtr CreateKillOnCloseJob()
        {
            IntPtr job = CreateJobObject(IntPtr.Zero, null);
            if (job == IntPtr.Zero) return IntPtr.Zero;
            var info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            int len = Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION));
            IntPtr ptr = Marshal.AllocHGlobal(len);
            try
            {
                Marshal.StructureToPtr(info, ptr, false);
                SetInformationJobObject(job, JobObjectExtendedLimitInformation, ptr, (uint)len);
            }
            finally { Marshal.FreeHGlobal(ptr); }
            return job;
        }
    }

    internal static class Paths
    {
        public static readonly string ExeDir = AppDomain.CurrentDomain.BaseDirectory;

        public static readonly string DataDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "FiveQThoughts");

        public static string WebViewDataDir => Path.Combine(DataDir, "WebView2");
        public static string WindowStateFile => Path.Combine(DataDir, "window.txt");
        public static string BackendLogFile => Path.Combine(DataDir, "backend.log");
    }

    internal static class L
    {
        private static readonly bool De =
            CultureInfo.CurrentUICulture.TwoLetterISOLanguageName.Equals("de", StringComparison.OrdinalIgnoreCase);

        public static string T(string de, string en) => De ? de : en;
    }

    public class MainForm : Form
    {
        private const int HOTKEY_ID = 0x5154;
        private const int HOTKEY_NEW_NOTE_ID = 0x5155;
        public static readonly uint WM_FIVEQ_SHOW = Native.RegisterWindowMessage("FiveQThoughts.ShowWindow");

        private readonly bool startHidden;
        private string targetUrl;
        private readonly bool ownsBackend;

        private readonly WebView2 webView;
        private CoreWebView2Environment webViewEnv;
        private readonly List<EditorForm> editorForms = new List<EditorForm>();
        private int editorCascadeIndex;
        private NotifyIcon trayIcon;
        private ToolStripMenuItem autostartItem;
        private Process backendProcess;
        private IntPtr backendJob = IntPtr.Zero;
        private StreamWriter backendLog;
        private bool allowExit;
        private bool hotkeyRegistered;
        private bool hotkeyNewNoteRegistered;
        private bool trayHintShown;
        private bool webViewReady;

        public MainForm(string url, bool hidden)
        {
            targetUrl = url;
            ownsBackend = string.IsNullOrEmpty(url);
            startHidden = hidden;

            Text = "FiveQThoughts — TheBrain Quick Thoughts (Ctrl+Alt+Q)";
            Icon = LoadAppIcon();
            MinimumSize = new Size(440, 500);
            StartPosition = FormStartPosition.Manual;
            BackColor = IsSystemDarkMode() ? Color.FromArgb(15, 20, 28) : Color.FromArgb(245, 247, 250);
            KeyPreview = true;
            RestoreWindowBounds();

            webView = new WebView2 { Dock = DockStyle.Fill, DefaultBackgroundColor = BackColor };
            Controls.Add(webView);

            SetupTrayIcon();
        }

        // ------------------------------------------------------------------ lifecycle

        protected override void SetVisibleCore(bool value)
        {
            // Start minimized to tray (--hidden, e.g. autostart): create handle but stay invisible.
            if (startHidden && !IsHandleCreated)
            {
                CreateHandle();
                value = false;
            }
            base.SetVisibleCore(value);
        }

        protected override void OnHandleCreated(EventArgs e)
        {
            base.OnHandleCreated(e);
            ApplyTitleBarTheme();
            hotkeyRegistered = Native.RegisterHotKey(Handle, HOTKEY_ID,
                Native.MOD_CONTROL | Native.MOD_ALT | Native.MOD_NOREPEAT, Native.VK_Q);
            hotkeyNewNoteRegistered = Native.RegisterHotKey(Handle, HOTKEY_NEW_NOTE_ID,
                Native.MOD_CONTROL | Native.MOD_ALT | Native.MOD_NOREPEAT, Native.VK_N);
            BeginInvoke(new Action(async () => await InitializeAsync()));
        }

        private async Task InitializeAsync()
        {
            ShowStatusPage(L.T("FiveQThoughts wird gestartet …", "Starting FiveQThoughts …"), null);

            try
            {
                Directory.CreateDirectory(Paths.DataDir);
                IntPtr _ = webView.Handle; // make sure the control exists even when started hidden (--hidden)
                webViewEnv = await CoreWebView2Environment.CreateAsync(null, Paths.WebViewDataDir);
                await webView.EnsureCoreWebView2Async(webViewEnv);
                ConfigureWebView(webView.CoreWebView2);
                webViewReady = true;
            }
            catch (Exception ex)
            {
                HandleMissingWebView2(ex);
                return;
            }

            ShowStatusPage(L.T("FiveQThoughts wird gestartet …", "Starting FiveQThoughts …"), null);

            if (ownsBackend)
            {
                string error = await Task.Run(() => StartBackend());
                if (error != null)
                {
                    ShowStatusPage(L.T("Backend konnte nicht gestartet werden", "Backend could not be started"), error);
                    return;
                }
            }

            webView.CoreWebView2.Navigate(targetUrl);
        }

        protected override void WndProc(ref Message m)
        {
            if (m.Msg == Native.WM_HOTKEY)
            {
                int id = m.WParam.ToInt32();
                if (id == HOTKEY_ID)
                {
                    ToggleWindow();
                    return;
                }
                if (id == HOTKEY_NEW_NOTE_ID)
                {
                    OpenNewNoteWindow();
                    return;
                }
            }
            if (WM_FIVEQ_SHOW != 0 && m.Msg == WM_FIVEQ_SHOW)
            {
                ShowAndActivate();
                return;
            }
            base.WndProc(ref m);
        }

        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            if (!allowExit && e.CloseReason == CloseReason.UserClosing)
            {
                // Keep running in the tray so Ctrl+Alt+Q stays active (like ⌘W on macOS)
                e.Cancel = true;
                SaveWindowBounds();
                Hide();
                if (!trayHintShown)
                {
                    trayHintShown = true;
                    trayIcon.ShowBalloonTip(3000, "FiveQThoughts",
                        L.T("Läuft im Infobereich weiter. Ctrl+Alt+Q holt das Fenster zurück.",
                            "Still running in the notification area. Press Ctrl+Alt+Q to bring it back."),
                        ToolTipIcon.Info);
                }
                return;
            }

            SaveWindowBounds();
            foreach (var ef in editorForms.ToArray())
            {
                try { ef.Close(); } catch { }
            }
            editorForms.Clear();
            if (hotkeyRegistered) Native.UnregisterHotKey(Handle, HOTKEY_ID);
            if (hotkeyNewNoteRegistered) Native.UnregisterHotKey(Handle, HOTKEY_NEW_NOTE_ID);
            trayIcon.Visible = false;
            trayIcon.Dispose();
            StopBackend();
            base.OnFormClosing(e);
        }

        protected override void OnKeyDown(KeyEventArgs e)
        {
            // Ctrl+W hides the window (analog to ⌘W)
            if (e.Control && e.KeyCode == Keys.W) { e.Handled = true; Close(); return; }
            // Ctrl+Q quits the app (analog to ⌘Q)
            if (e.Control && e.KeyCode == Keys.Q) { e.Handled = true; QuitApp(); return; }
            base.OnKeyDown(e);
        }

        public void QuitApp()
        {
            allowExit = true;
            Close();
        }

        // ------------------------------------------------------------------ window toggling

        private void ToggleWindow()
        {
            if (Visible && WindowState != FormWindowState.Minimized && Native.GetForegroundWindow() == Handle)
            {
                SaveWindowBounds();
                Hide();
            }
            else
            {
                ShowAndActivate();
            }
        }

        public void ShowAndActivate()
        {
            if (!Visible) Show();
            if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
            Activate();
            BringToFront();
            Native.SetForegroundWindow(Handle);
            if (webViewReady) webView.Focus();
        }

        // ------------------------------------------------------------------ WebView2

        private void ConfigureWebView(CoreWebView2 core)
        {
            core.Settings.AreDevToolsEnabled = true;
            core.Settings.IsStatusBarEnabled = false;
            core.Settings.IsZoomControlEnabled = true;
            core.Settings.AreBrowserAcceleratorKeysEnabled = true;

            // target="_blank" / window.open → independent native window for local app URLs, else system browser
            core.NewWindowRequested += async (s, e) =>
            {
                if (IsAppUrl(e.Uri) && webViewEnv != null)
                {
                    var deferral = e.GetDeferral();
                    try
                    {
                        var editor = CreateEditorForm();
                        editor.Show();
                        await editor.InitializeForPopupAsync(webViewEnv);
                        e.NewWindow = editor.CoreWebView2;
                        e.Handled = true;
                        editor.ActivateAndFocus();
                    }
                    catch
                    {
                        e.Handled = true;
                    }
                    finally
                    {
                        deferral.Complete();
                    }
                    return;
                }
                e.Handled = true;
                OpenExternal(e.Uri);
            };

            // Messages from web UI (e.g. Quit button or Ctrl+Q)
            core.WebMessageReceived += (s, e) =>
            {
                try
                {
                    string msg = e.TryGetWebMessageAsString();
                    if (msg == "quit") QuitApp();
                }
                catch { }
            };

            // Links that would navigate away from the local UI → default system browser
            core.NavigationStarting += (s, e) =>
            {
                if (!IsAppUrl(e.Uri))
                {
                    e.Cancel = true;
                    OpenExternal(e.Uri);
                }
            };

            // Allow clipboard access for our own local UI (navigator.clipboard)
            core.PermissionRequested += (s, e) =>
            {
                if (e.PermissionKind == CoreWebView2PermissionKind.ClipboardRead && IsAppUrl(e.Uri))
                    e.State = CoreWebView2PermissionState.Allow;
            };

            core.ProcessFailed += (s, e) =>
            {
                if (e.ProcessFailedKind == CoreWebView2ProcessFailedKind.BrowserProcessExited) return;
                try { core.Reload(); } catch { }
            };
        }

        internal bool IsAppUrl(string uri)
        {
            if (string.IsNullOrEmpty(uri)) return true;
            if (uri.StartsWith("data:", StringComparison.OrdinalIgnoreCase) ||
                uri.StartsWith("about:", StringComparison.OrdinalIgnoreCase) ||
                uri.StartsWith("blob:", StringComparison.OrdinalIgnoreCase)) return true;
            if (string.IsNullOrEmpty(targetUrl)) return false;
            try
            {
                var a = new Uri(uri);
                var b = new Uri(targetUrl);
                return a.Scheme == b.Scheme && a.Host == b.Host && a.Port == b.Port;
            }
            catch { return false; }
        }

        internal static void OpenExternal(string uri)
        {
            if (string.IsNullOrEmpty(uri)) return;
            if (!(uri.StartsWith("http://", StringComparison.OrdinalIgnoreCase) ||
                  uri.StartsWith("https://", StringComparison.OrdinalIgnoreCase) ||
                  uri.StartsWith("mailto:", StringComparison.OrdinalIgnoreCase) ||
                  uri.StartsWith("brain://", StringComparison.OrdinalIgnoreCase))) return;
            try { Process.Start(new ProcessStartInfo(uri) { UseShellExecute = true }); } catch { }
        }

        private async void ShowAbout()
        {
            ShowAndActivate();
            if (!webViewReady) return;
            try { await webView.CoreWebView2.ExecuteScriptAsync("window.showAbout && window.showAbout()"); }
            catch { }
        }

        private async void ShowSettings()
        {
            ShowAndActivate();
            if (!webViewReady) return;
            try { await webView.CoreWebView2.ExecuteScriptAsync("window.showSettings && window.showSettings()"); }
            catch { }
        }

        private void ReloadPage()
        {
            if (!webViewReady) return;
            if (string.IsNullOrEmpty(webView.CoreWebView2.Source) || webView.CoreWebView2.Source.StartsWith("data:"))
            {
                if (!string.IsNullOrEmpty(targetUrl)) webView.CoreWebView2.Navigate(targetUrl);
            }
            else
            {
                webView.CoreWebView2.Reload();
            }
        }

        private void ShowStatusPage(string headline, string detail)
        {
            if (!webViewReady) return;
            bool dark = IsSystemDarkMode();
            string bg = dark ? "#0f141c" : "#f5f7fa";
            string fg = dark ? "#e5e7eb" : "#1f2937";
            string html =
                "<!DOCTYPE html><html><head><meta charset='utf-8'><style>" +
                "body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;" +
                "font-family:'Segoe UI',sans-serif;background:" + bg + ";color:" + fg + "}" +
                ".b{font-size:56px}.box{text-align:center;max-width:640px;padding:24px}" +
                "pre{white-space:pre-wrap;text-align:left;font-size:12px;opacity:.8}</style></head><body>" +
                "<div class='box'><div class='b'>⚡</div><h2>" + WebUtility.HtmlEncode(headline) + "</h2>" +
                (detail != null ? "<pre>" + WebUtility.HtmlEncode(detail) + "</pre>" : "") +
                "</div></body></html>";
            webView.CoreWebView2.NavigateToString(html);
        }

        private void HandleMissingWebView2(Exception ex)
        {
            var res = MessageBox.Show(this,
                L.T("Die Microsoft Edge WebView2 Runtime wurde nicht gefunden oder konnte nicht gestartet werden.\n\n" +
                    "Soll die Download-Seite geöffnet werden?\n\nDetails: ",
                    "The Microsoft Edge WebView2 Runtime was not found or could not be started.\n\n" +
                    "Open the download page?\n\nDetails: ") + ex.Message,
                "FiveQThoughts", MessageBoxButtons.YesNo, MessageBoxIcon.Warning);
            if (res == DialogResult.Yes)
                OpenExternal("https://developer.microsoft.com/microsoft-edge/webview2/");
            QuitApp();
        }

        // ------------------------------------------------------------------ backend (Python)

        /// <summary>Starts the backend on a free port. Returns null on success, else an error text.</summary>
        private string StartBackend()
        {
            int port = FindFreePort(11525);
            ProcessStartInfo psi = ResolveBackend(port, out string description);
            if (psi == null)
            {
                return L.T(
                    "Weder backend\\FiveQThoughts-backend.exe noch app.py (mit Python) wurden gefunden.\nGesucht ab: ",
                    "Neither backend\\FiveQThoughts-backend.exe nor app.py (with Python) was found.\nSearched from: ") + Paths.ExeDir;
            }

            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            psi.RedirectStandardOutput = true;
            psi.RedirectStandardError = true;
            psi.StandardOutputEncoding = Encoding.UTF8;
            psi.StandardErrorEncoding = Encoding.UTF8;
            psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
            psi.EnvironmentVariables["PYTHONUNBUFFERED"] = "1";
            psi.EnvironmentVariables["FIVEQ_HOST"] = "windows";

            try
            {
                Directory.CreateDirectory(Paths.DataDir);
                backendLog = new StreamWriter(Paths.BackendLogFile, false, new UTF8Encoding(false)) { AutoFlush = true };
                backendLog.WriteLine($"[{DateTime.Now:s}] {description}");
            }
            catch { backendLog = null; }

            try
            {
                backendProcess = new Process { StartInfo = psi, EnableRaisingEvents = true };
                backendProcess.OutputDataReceived += (s, e) => LogBackend(e.Data);
                backendProcess.ErrorDataReceived += (s, e) => LogBackend(e.Data);
                backendProcess.Start();
                backendProcess.BeginOutputReadLine();
                backendProcess.BeginErrorReadLine();

                backendJob = Native.CreateKillOnCloseJob();
                if (backendJob != IntPtr.Zero)
                    Native.AssignProcessToJobObject(backendJob, backendProcess.Handle);
            }
            catch (Exception ex)
            {
                return description + "\n\n" + ex.Message;
            }

            targetUrl = "http://127.0.0.1:" + port;
            var sw = Stopwatch.StartNew();
            while (sw.Elapsed < TimeSpan.FromSeconds(30))
            {
                if (backendProcess.HasExited)
                {
                    return description + "\n\n" + L.T("Prozess beendet mit Code ", "Process exited with code ") +
                           backendProcess.ExitCode + "\n" + ReadLogTail();
                }
                if (IsPortOpen(port)) return null;
                Thread.Sleep(100);
            }
            return description + "\n\nTimeout.\n" + ReadLogTail();
        }

        private static ProcessStartInfo ResolveBackend(int port, out string description)
        {
            string args = "--no-browser --port " + port;

            // 1) Bundled backend (installer / portable build)
            string bundled = Path.Combine(Paths.ExeDir, "backend", "FiveQThoughts-backend.exe");
            if (File.Exists(bundled))
            {
                description = bundled + " " + args;
                return new ProcessStartInfo(bundled, args) { WorkingDirectory = Path.GetDirectoryName(bundled) };
            }

            // 2) Development: app.py next to the exe or in a parent directory (e.g. native/windows/bin/...)
            string dir = Paths.ExeDir;
            for (int i = 0; i < 6 && dir != null; i++)
            {
                string appPy = Path.Combine(dir, "app.py");
                if (File.Exists(appPy))
                {
                    string python = FindPython();
                    if (python == null) break;
                    string fullArgs = "\"" + appPy + "\" " + args;
                    description = python + " " + fullArgs;
                    return new ProcessStartInfo(python, fullArgs) { WorkingDirectory = dir };
                }
                dir = Path.GetDirectoryName(dir.TrimEnd(Path.DirectorySeparatorChar));
            }

            description = null;
            return null;
        }

        private static string FindPython()
        {
            string path = Environment.GetEnvironmentVariable("PATH") ?? "";
            foreach (string name in new[] { "python.exe", "py.exe", "python3.exe" })
            {
                foreach (string p in path.Split(';'))
                {
                    if (string.IsNullOrWhiteSpace(p)) continue;
                    try
                    {
                        string candidate = Path.Combine(p.Trim().Trim('"'), name);
                        // Skip the Microsoft Store alias stub (WindowsApps), it opens the Store instead of Python
                        if (File.Exists(candidate) && candidate.IndexOf("WindowsApps", StringComparison.OrdinalIgnoreCase) < 0)
                            return candidate;
                    }
                    catch { }
                }
            }
            return null;
        }

        private readonly object logLock = new object();
        private readonly List<string> logTail = new List<string>();

        private void LogBackend(string line)
        {
            if (line == null) return;
            lock (logLock)
            {
                logTail.Add(line);
                if (logTail.Count > 30) logTail.RemoveAt(0);
                try { backendLog?.WriteLine(line); } catch { }
            }
        }

        private string ReadLogTail()
        {
            lock (logLock) { return string.Join("\n", logTail); }
        }

        private void StopBackend()
        {
            try
            {
                if (backendProcess != null && !backendProcess.HasExited)
                {
                    backendProcess.Kill();
                    backendProcess.WaitForExit(2000);
                }
            }
            catch { }
            try { backendLog?.Dispose(); } catch { }
        }

        private static int FindFreePort(int preferred)
        {
            foreach (int p in new[] { preferred, preferred + 1, preferred + 2, 0 })
            {
                try
                {
                    var l = new TcpListener(IPAddress.Loopback, p);
                    l.Start();
                    int port = ((IPEndPoint)l.LocalEndpoint).Port;
                    l.Stop();
                    return port;
                }
                catch { }
            }
            return preferred;
        }

        private static bool IsPortOpen(int port)
        {
            try
            {
                using (var client = new TcpClient())
                {
                    var ar = client.BeginConnect(IPAddress.Loopback, port, null, null);
                    if (!ar.AsyncWaitHandle.WaitOne(TimeSpan.FromMilliseconds(200))) return false;
                    client.EndConnect(ar);
                    return true;
                }
            }
            catch { return false; }
        }

        // ------------------------------------------------------------------ tray

        private void SetupTrayIcon()
        {
            var menu = new ContextMenuStrip();

            var toggleItem = new ToolStripMenuItem(L.T("FiveQThoughts anzeigen/verbergen", "Show/hide FiveQThoughts"))
            {
                ShortcutKeyDisplayString = "Ctrl+Alt+Q",
                Font = new Font(menu.Font, FontStyle.Bold)
            };
            toggleItem.Click += (s, e) => ToggleWindow();
            menu.Items.Add(toggleItem);

            var newNoteItem = new ToolStripMenuItem(L.T("＋ Neue Notiz", "＋ New Note"))
            {
                ShortcutKeyDisplayString = "Ctrl+Alt+N"
            };
            newNoteItem.Click += (s, e) => OpenNewNoteWindow();
            menu.Items.Add(newNoteItem);

            var reloadItem = new ToolStripMenuItem(L.T("Aktualisieren", "Reload"));
            reloadItem.Click += (s, e) => ReloadPage();
            menu.Items.Add(reloadItem);

            var settingsItem = new ToolStripMenuItem(L.T("Einstellungen …", "Settings …"));
            settingsItem.Click += (s, e) => ShowSettings();
            menu.Items.Add(settingsItem);

            var browserItem = new ToolStripMenuItem(L.T("Im Browser öffnen", "Open in browser"));
            browserItem.Click += (s, e) => { if (!string.IsNullOrEmpty(targetUrl)) OpenExternal(targetUrl); };
            menu.Items.Add(browserItem);

            menu.Items.Add(new ToolStripSeparator());

            autostartItem = new ToolStripMenuItem(L.T("Mit Windows starten", "Start with Windows"))
            {
                CheckOnClick = false,
                Checked = Autostart.IsEnabled()
            };
            autostartItem.Click += (s, e) =>
            {
                Autostart.Set(!Autostart.IsEnabled());
                autostartItem.Checked = Autostart.IsEnabled();
            };
            menu.Items.Add(autostartItem);

            var logItem = new ToolStripMenuItem(L.T("Datenordner öffnen", "Open data folder"));
            logItem.Click += (s, e) =>
            {
                try
                {
                    string roaming = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "FiveQThoughts");
                    string folder = Directory.Exists(roaming) ? roaming : Paths.DataDir;
                    Directory.CreateDirectory(folder);
                    Process.Start(new ProcessStartInfo(folder) { UseShellExecute = true });
                }
                catch { }
            };
            menu.Items.Add(logItem);

            menu.Items.Add(new ToolStripSeparator());

            var aboutItem = new ToolStripMenuItem(L.T("Über FiveQThoughts", "About FiveQThoughts"));
            aboutItem.Click += (s, e) => ShowAbout();
            menu.Items.Add(aboutItem);

            var exitItem = new ToolStripMenuItem(L.T("Beenden", "Quit"));
            exitItem.Click += (s, e) => QuitApp();
            menu.Items.Add(exitItem);

            menu.Opening += (s, e) => autostartItem.Checked = Autostart.IsEnabled();

            trayIcon = new NotifyIcon
            {
                Text = "FiveQThoughts (Ctrl+Alt+Q)",
                Icon = new Icon(Icon, SystemInformation.SmallIconSize),
                ContextMenuStrip = menu,
                Visible = true
            };
            trayIcon.MouseClick += (s, e) => { if (e.Button == MouseButtons.Left) ToggleWindow(); };
        }

        // ------------------------------------------------------------------ editor windows

        private EditorForm CreateEditorForm()
        {
            int offset = (editorCascadeIndex % 8) * 28;
            editorCascadeIndex++;
            var editor = new EditorForm(this, offset);
            editorForms.Add(editor);
            editor.FormClosed += (s, e) =>
            {
                editorForms.Remove(editor);
                if (editorForms.Count == 0) editorCascadeIndex = 0;
            };
            return editor;
        }

        public async void OpenNewNoteWindow()
        {
            if (!webViewReady || webViewEnv == null || string.IsNullOrEmpty(targetUrl))
            {
                ShowAndActivate();
                return;
            }
            try
            {
                var editor = CreateEditorForm();
                editor.Show();
                editor.ActivateAndFocus();
                string url = targetUrl.TrimEnd('/') + "/?mode=editor";
                await editor.InitializeAndNavigateAsync(webViewEnv, url);
            }
            catch { }
        }

        // ------------------------------------------------------------------ helpers

        internal static Icon LoadAppIcon()
        {
            try
            {
                using (var s = typeof(MainForm).Assembly.GetManifestResourceStream("FiveQThoughts.ico"))
                {
                    if (s != null) return new Icon(s);
                }
            }
            catch { }
            return Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        }

        internal static bool IsSystemDarkMode()
        {
            try
            {
                using (var key = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"))
                {
                    object v = key?.GetValue("AppsUseLightTheme");
                    if (v is int i) return i == 0;
                }
            }
            catch { }
            return false;
        }

        private void ApplyTitleBarTheme()
        {
            try
            {
                int dark = IsSystemDarkMode() ? 1 : 0;
                // DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (Win10 20H1+ / Win11)
                Native.DwmSetWindowAttribute(Handle, 20, ref dark, sizeof(int));
            }
            catch { }
        }

        private void RestoreWindowBounds()
        {
            Size = new Size(1180, 840);
            Rectangle wa = Screen.PrimaryScreen.WorkingArea;
            Location = new Point(wa.Left + Math.Max(0, (wa.Width - Width) / 2), wa.Top + Math.Max(0, (wa.Height - Height) / 2));
            try
            {
                if (!File.Exists(Paths.WindowStateFile)) return;
                string[] p = File.ReadAllText(Paths.WindowStateFile).Trim().Split(',');
                if (p.Length < 5) return;
                var r = new Rectangle(int.Parse(p[0]), int.Parse(p[1]), int.Parse(p[2]), int.Parse(p[3]));
                bool onScreen = false;
                foreach (var scr in Screen.AllScreens)
                    if (scr.WorkingArea.IntersectsWith(r)) { onScreen = true; break; }
                if (!onScreen || r.Width < MinimumSize.Width || r.Height < MinimumSize.Height) return;
                Bounds = r;
                if (p[4] == "1") WindowState = FormWindowState.Maximized;
            }
            catch { }
        }

        private void SaveWindowBounds()
        {
            try
            {
                if (!IsHandleCreated || WindowState == FormWindowState.Minimized) return;
                Rectangle r = WindowState == FormWindowState.Normal ? Bounds : RestoreBounds;
                if (r.Width <= 0 || r.Height <= 0) return;
                Directory.CreateDirectory(Paths.DataDir);
                File.WriteAllText(Paths.WindowStateFile,
                    $"{r.X},{r.Y},{r.Width},{r.Height},{(WindowState == FormWindowState.Maximized ? 1 : 0)}");
            }
            catch { }
        }
    }

    internal class EditorForm : Form
    {
        private readonly MainForm mainForm;
        private readonly WebView2 webView;
        private bool webViewReady;

        public CoreWebView2 CoreWebView2 => webView.CoreWebView2;

        public EditorForm(MainForm mainForm, int cascadeOffset)
        {
            this.mainForm = mainForm;
            Text = L.T("Neuer Quick Thought — FiveQThoughts", "New Quick Thought — FiveQThoughts");
            Icon = MainForm.LoadAppIcon();
            Size = new Size(720, 640);
            MinimumSize = new Size(420, 380);
            StartPosition = FormStartPosition.Manual;
            BackColor = MainForm.IsSystemDarkMode() ? Color.FromArgb(15, 20, 28) : Color.FromArgb(245, 247, 250);
            KeyPreview = true;

            Rectangle wa = Screen.FromPoint(Cursor.Position).WorkingArea;
            int x = wa.Left + Math.Max(0, (wa.Width - Width) / 2) + cascadeOffset;
            int y = wa.Top + Math.Max(0, (wa.Height - Height) / 2) + cascadeOffset;
            if (x + Width > wa.Right) x = Math.Max(wa.Left, wa.Right - Width);
            if (y + Height > wa.Bottom) y = Math.Max(wa.Top, wa.Bottom - Height);
            Location = new Point(x, y);

            webView = new WebView2 { Dock = DockStyle.Fill, DefaultBackgroundColor = BackColor };
            Controls.Add(webView);
        }

        protected override void OnHandleCreated(EventArgs e)
        {
            base.OnHandleCreated(e);
            try
            {
                int dark = MainForm.IsSystemDarkMode() ? 1 : 0;
                Native.DwmSetWindowAttribute(Handle, 20, ref dark, sizeof(int));
            }
            catch { }
        }

        public async Task InitializeForPopupAsync(CoreWebView2Environment env)
        {
            IntPtr _ = webView.Handle;
            await webView.EnsureCoreWebView2Async(env);
            ConfigureWebView(webView.CoreWebView2);
            webViewReady = true;
        }

        public async Task InitializeAndNavigateAsync(CoreWebView2Environment env, string url)
        {
            await InitializeForPopupAsync(env);
            webView.CoreWebView2.Navigate(url);
        }

        public void ActivateAndFocus()
        {
            if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
            Activate();
            BringToFront();
            Native.SetForegroundWindow(Handle);
            if (webViewReady) webView.Focus();
        }

        private void ConfigureWebView(CoreWebView2 core)
        {
            core.Settings.AreDevToolsEnabled = true;
            core.Settings.IsStatusBarEnabled = false;
            core.Settings.IsZoomControlEnabled = true;
            core.Settings.AreBrowserAcceleratorKeysEnabled = true;

            core.WindowCloseRequested += (s, e) => Close();

            core.DocumentTitleChanged += (s, e) =>
            {
                if (!string.IsNullOrWhiteSpace(core.DocumentTitle))
                    Text = core.DocumentTitle;
            };

            core.NewWindowRequested += (s, e) =>
            {
                e.Handled = true;
                MainForm.OpenExternal(e.Uri);
            };

            core.NavigationStarting += (s, e) =>
            {
                if (!mainForm.IsAppUrl(e.Uri))
                {
                    e.Cancel = true;
                    MainForm.OpenExternal(e.Uri);
                }
            };

            core.PermissionRequested += (s, e) =>
            {
                if (e.PermissionKind == CoreWebView2PermissionKind.ClipboardRead && mainForm.IsAppUrl(e.Uri))
                    e.State = CoreWebView2PermissionState.Allow;
            };

            core.WebMessageReceived += (s, e) =>
            {
                try
                {
                    string msg = e.TryGetWebMessageAsString();
                    if (msg == "quit") mainForm.QuitApp();
                }
                catch { }
            };
        }

        protected override void OnKeyDown(KeyEventArgs e)
        {
            if (e.Control && e.KeyCode == Keys.W) { e.Handled = true; Close(); return; }
            if (e.Control && e.KeyCode == Keys.Q) { e.Handled = true; mainForm.QuitApp(); return; }
            base.OnKeyDown(e);
        }
    }

    internal static class Autostart
    {
        private const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
        private const string ValueName = "FiveQThoughts";

        public static bool IsEnabled()
        {
            try
            {
                using (var key = Registry.CurrentUser.OpenSubKey(RunKey))
                    return key?.GetValue(ValueName) != null;
            }
            catch { return false; }
        }

        public static void Set(bool enabled)
        {
            try
            {
                using (var key = Registry.CurrentUser.CreateSubKey(RunKey))
                {
                    if (enabled) key.SetValue(ValueName, "\"" + Application.ExecutablePath + "\" --hidden");
                    else key.DeleteValue(ValueName, false);
                }
            }
            catch { }
        }
    }

    public static class Program
    {
        [STAThread]
        public static void Main(string[] args)
        {
            string url = null;
            bool hidden = false;
            for (int i = 0; i < args.Length; i++)
            {
                if (args[i] == "--url" && i + 1 < args.Length) url = args[++i];
                else if (args[i] == "--hidden") hidden = true;
            }

            using (var mutex = new Mutex(true, @"Local\FiveQThoughts.SingleInstance", out bool isFirst))
            {
                if (!isFirst)
                {
                    // Already running → bring the existing window to the front
                    Native.AllowSetForegroundWindow(-1); // ASFW_ANY
                    Native.PostMessage(Native.HWND_BROADCAST, MainForm.WM_FIVEQ_SHOW, IntPtr.Zero, IntPtr.Zero);
                    return;
                }

                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Application.Run(new MainForm(url, hidden));
                GC.KeepAlive(mutex);
            }
        }
    }
}
