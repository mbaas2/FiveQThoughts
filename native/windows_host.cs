using System;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Net.Sockets;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;

namespace FiveQThoughtsHost
{
    public class MainForm : Form
    {
        private const int WM_HOTKEY = 0x0312;
        private const int HOTKEY_ID = 0x5154;
        private const uint MOD_ALT = 0x0001;
        private const uint MOD_CONTROL = 0x0002;
        private const uint MOD_NOREPEAT = 0x4000;
        private const uint VK_Q = 0x51;

        [DllImport("user32.dll")]
        private static extern bool RegisterHotKey(IntPtr hWnd, int id, uint fsModifiers, uint vk);

        [DllImport("user32.dll")]
        private static extern bool UnregisterHotKey(IntPtr hWnd, int id);

        [DllImport("user32.dll")]
        private static extern bool SetForegroundWindow(IntPtr hWnd);

        [DllImport("user32.dll", CharSet = CharSet.Auto)]
        private static extern bool DestroyIcon(IntPtr handle);

        private string targetUrl;
        private NotifyIcon trayIcon;
        private ContextMenuStrip trayMenu;
        private Control browserView;
        private Process backendProcess;
        private Process appWindowProcess;
        private IntPtr trackedWindowHandle = IntPtr.Zero;
        private bool allowExit = false;
        private Icon appIcon;

        [DllImport("user32.dll")]
        private static extern bool IsWindow(IntPtr hWnd);

        [DllImport("user32.dll")]
        private static extern bool IsIconic(IntPtr hWnd);

        [DllImport("user32.dll")]
        private static extern IntPtr GetForegroundWindow();

        [DllImport("user32.dll")]
        private static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

        private delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

        [DllImport("user32.dll")]
        private static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

        [DllImport("user32.dll")]
        private static extern bool IsWindowVisible(IntPtr hWnd);

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern int GetWindowText(IntPtr hWnd, System.Text.StringBuilder lpString, int nMaxCount);

        [DllImport("user32.dll")]
        private static extern int GetWindowTextLength(IntPtr hWnd);

        private const int SW_MINIMIZE = 6;
        private const int SW_RESTORE = 9;

        public MainForm(string url)
        {
            this.targetUrl = url;
            this.appIcon = CreateLightningIcon();

            this.Text = "FiveQThoughts — TheBrain Quick Thoughts (Ctrl+Alt+Q)";
            this.Icon = this.appIcon;
            this.Size = new Size(1200, 860);
            this.MinimumSize = new Size(440, 500);
            this.StartPosition = FormStartPosition.CenterScreen;
            this.BackColor = Color.FromArgb(15, 20, 28);

            EnsureBackendRunning();
            SetupTrayIcon();

            // Launch modern Chromium-based Edge/Chrome App window while keeping this native tray + hotkey host alive
            if (LaunchModernAppWindow())
            {
                this.WindowState = FormWindowState.Minimized;
                this.ShowInTaskbar = false;
                this.Opacity = 0;
            }
            else
            {
                InitializeBrowserControl();
            }
        }

        protected override void SetVisibleCore(bool value)
        {
            if (this.Opacity == 0 && value)
            {
                base.SetVisibleCore(false);
                if (!this.IsHandleCreated) CreateHandle();
                return;
            }
            base.SetVisibleCore(value);
        }

        protected override void OnHandleCreated(EventArgs e)
        {
            base.OnHandleCreated(e);
            RegisterHotKey(this.Handle, HOTKEY_ID, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_Q);
        }

        protected override void WndProc(ref Message m)
        {
            if (m.Msg == WM_HOTKEY && m.WParam.ToInt32() == HOTKEY_ID)
            {
                ToggleWindow();
                return;
            }
            base.WndProc(ref m);
        }

        private IntPtr FindFiveQWindow()
        {
            if (trackedWindowHandle != IntPtr.Zero && IsWindow(trackedWindowHandle))
            {
                return trackedWindowHandle;
            }

            IntPtr found = IntPtr.Zero;
            EnumWindows((hWnd, lParam) =>
            {
                if (hWnd == this.Handle) return true;
                if (!IsWindowVisible(hWnd)) return true;
                int len = GetWindowTextLength(hWnd);
                if (len <= 0) return true;

                System.Text.StringBuilder sb = new System.Text.StringBuilder(len + 1);
                GetWindowText(hWnd, sb, sb.Capacity);
                string title = sb.ToString();
                if (title.IndexOf("FiveQThoughts", StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    found = hWnd;
                    return false;
                }
                return true;
            }, IntPtr.Zero);

            if (found != IntPtr.Zero)
            {
                trackedWindowHandle = found;
            }
            return found;
        }

        private bool LaunchModernAppWindow()
        {
            string[] bases = new string[]
            {
                Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),
                Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86),
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData)
            };

            string[] relPaths = new string[]
            {
                @"Microsoft\Edge\Application\msedge.exe",
                @"Google\Chrome\Application\chrome.exe",
                @"BraveSoftware\Brave-Browser\Application\brave.exe"
            };

            string profileDir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "FiveQThoughts",
                "AppProfile"
            );

            foreach (string b in bases)
            {
                if (string.IsNullOrEmpty(b)) continue;
                foreach (string rel in relPaths)
                {
                    string candidate = Path.Combine(b, rel);
                    if (File.Exists(candidate))
                    {
                        try
                        {
                            Directory.CreateDirectory(profileDir);
                            ProcessStartInfo psi = new ProcessStartInfo
                            {
                                FileName = candidate,
                                Arguments = "--app=\"" + this.targetUrl + "\" --window-size=1200,860 --user-data-dir=\"" + profileDir + "\"",
                                UseShellExecute = false
                            };
                            appWindowProcess = Process.Start(psi);
                            return true;
                        }
                        catch { }
                    }
                }
            }
            return false;
        }

        private void ToggleWindow()
        {
            if (this.Opacity == 0)
            {
                IntPtr hWnd = FindFiveQWindow();
                if (hWnd != IntPtr.Zero)
                {
                    IntPtr fg = GetForegroundWindow();
                    if (fg == hWnd && !IsIconic(hWnd))
                    {
                        ShowWindow(hWnd, SW_MINIMIZE);
                    }
                    else
                    {
                        ShowWindow(hWnd, SW_RESTORE);
                        SetForegroundWindow(hWnd);
                    }
                }
                else
                {
                    LaunchModernAppWindow();
                }
                return;
            }

            if (this.Visible && this.WindowState != FormWindowState.Minimized && Form.ActiveForm == this)
            {
                this.Hide();
            }
            else
            {
                ShowAndActivate();
            }
        }

        private void ShowAndActivate()
        {
            if (this.Opacity == 0)
            {
                IntPtr hWnd = FindFiveQWindow();
                if (hWnd != IntPtr.Zero)
                {
                    ShowWindow(hWnd, SW_RESTORE);
                    SetForegroundWindow(hWnd);
                }
                else
                {
                    LaunchModernAppWindow();
                }
                return;
            }

            if (!this.Visible)
            {
                this.Show();
            }
            if (this.WindowState == FormWindowState.Minimized)
            {
                this.WindowState = FormWindowState.Normal;
            }
            this.BringToFront();
            this.Activate();
            SetForegroundWindow(this.Handle);
        }

        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            if (!allowExit && e.CloseReason == CloseReason.UserClosing)
            {
                // Keep running in system tray so Ctrl+Alt+Q stays active
                e.Cancel = true;
                this.Hide();
                return;
            }

            UnregisterHotKey(this.Handle, HOTKEY_ID);
            if (trayIcon != null)
            {
                trayIcon.Visible = false;
                trayIcon.Dispose();
            }
            if (backendProcess != null && !backendProcess.HasExited)
            {
                try { backendProcess.Kill(); } catch { }
            }
            base.OnFormClosing(e);
        }

        private void SetupTrayIcon()
        {
            trayMenu = new ContextMenuStrip();
            ToolStripMenuItem toggleItem = new ToolStripMenuItem("FiveQThoughts anzeigen/verbergen (Ctrl+Alt+Q)");
            toggleItem.Click += (s, e) => ToggleWindow();
            trayMenu.Items.Add(toggleItem);

            ToolStripMenuItem reloadItem = new ToolStripMenuItem("Aktualisieren");
            reloadItem.Click += (s, e) => ReloadBrowser();
            trayMenu.Items.Add(reloadItem);

            trayMenu.Items.Add(new ToolStripSeparator());

            ToolStripMenuItem exitItem = new ToolStripMenuItem("Beenden");
            exitItem.Click += (s, e) =>
            {
                allowExit = true;
                Application.Exit();
            };
            trayMenu.Items.Add(exitItem);

            trayIcon = new NotifyIcon();
            trayIcon.Text = "FiveQThoughts (Ctrl+Alt+Q)";
            trayIcon.Icon = this.appIcon;
            trayIcon.ContextMenuStrip = trayMenu;
            trayIcon.Visible = true;
            trayIcon.DoubleClick += (s, e) => ShowAndActivate();
        }

        private void InitializeBrowserControl()
        {
            // Try modern WebView2 if present in the same directory or GAC, otherwise use configured IE11/Edge WebBrowser
            SetBrowserFeatureControl();

            WebBrowser wb = new WebBrowser();
            wb.Dock = DockStyle.Fill;
            wb.ScriptErrorsSuppressed = true;
            wb.IsWebBrowserContextMenuEnabled = true;
            wb.WebBrowserShortcutsEnabled = true;
            this.Controls.Add(wb);
            this.browserView = wb;
            wb.Navigate(this.targetUrl);
        }

        private void ReloadBrowser()
        {
            WebBrowser wb = this.browserView as WebBrowser;
            if (wb != null)
            {
                wb.Refresh();
            }
        }

        private static void SetBrowserFeatureControl()
        {
            try
            {
                string exeName = Path.GetFileName(Process.GetCurrentProcess().MainModule.FileName);
                using (var key = Microsoft.Win32.Registry.CurrentUser.CreateSubKey(
                    @"Software\Microsoft\Internet Explorer\Main\FeatureControl\FEATURE_BROWSER_EMULATION"))
                {
                    if (key != null)
                    {
                        key.SetValue(exeName, 11001, Microsoft.Win32.RegistryValueKind.DWord);
                    }
                }
            }
            catch { }
        }

        private static bool IsPortOpen(int port)
        {
            try
            {
                using (TcpClient client = new TcpClient())
                {
                    var result = client.BeginConnect("127.0.0.1", port, null, null);
                    bool success = result.AsyncWaitHandle.WaitOne(TimeSpan.FromMilliseconds(150));
                    if (!success) return false;
                    client.EndConnect(result);
                    return true;
                }
            }
            catch
            {
                return false;
            }
        }

        private void EnsureBackendRunning()
        {
            try
            {
                Uri uri = new Uri(this.targetUrl);
                int port = uri.Port;
                if (IsPortOpen(port)) return;

                string exePath = Assembly.GetExecutingAssembly().Location;
                string projectDir = Path.GetDirectoryName(exePath);
                string appPy = Path.Combine(projectDir, "app.py");
                if (!File.Exists(appPy)) return;

                ProcessStartInfo psi = new ProcessStartInfo
                {
                    FileName = "python",
                    Arguments = "\"" + appPy + "\" --no-browser --port " + port,
                    WorkingDirectory = projectDir,
                    UseShellExecute = false,
                    CreateNoWindow = true
                };
                backendProcess = Process.Start(psi);

                for (int i = 0; i < 25; i++)
                {
                    if (IsPortOpen(port)) break;
                    Thread.Sleep(100);
                }
            }
            catch { }
        }

        private static Icon CreateLightningIcon()
        {
            using (Bitmap bmp = new Bitmap(64, 64))
            using (Graphics g = Graphics.FromImage(bmp))
            {
                g.SmoothingMode = SmoothingMode.AntiAlias;
                Rectangle rect = new Rectangle(4, 4, 56, 56);

                using (GraphicsPath path = RoundedRect(rect, 14))
                using (LinearGradientBrush brush = new LinearGradientBrush(
                    rect,
                    Color.FromArgb(59, 130, 246),
                    Color.FromArgb(29, 78, 216),
                    45f))
                {
                    g.FillPath(brush, path);
                }

                PointF[] bolt = new PointF[]
                {
                    new PointF(36f, 10f),
                    new PointF(19f, 33f),
                    new PointF(31f, 33f),
                    new PointF(27f, 54f),
                    new PointF(45f, 30f),
                    new PointF(33f, 30f)
                };
                g.FillPolygon(Brushes.White, bolt);

                IntPtr hIcon = bmp.GetHicon();
                Icon tempIcon = Icon.FromHandle(hIcon);
                Icon cloned = (Icon)tempIcon.Clone();
                DestroyIcon(hIcon);
                return cloned;
            }
        }

        private static GraphicsPath RoundedRect(Rectangle bounds, int radius)
        {
            int diameter = radius * 2;
            Size size = new Size(diameter, diameter);
            Rectangle arc = new Rectangle(bounds.Location, size);
            GraphicsPath path = new GraphicsPath();

            path.AddArc(arc, 180, 90);
            arc.X = bounds.Right - diameter;
            path.AddArc(arc, 270, 90);
            arc.Y = bounds.Bottom - diameter;
            path.AddArc(arc, 0, 90);
            arc.X = bounds.Left;
            path.AddArc(arc, 90, 90);
            path.CloseFigure();
            return path;
        }
    }

    public static class Program
    {
        [STAThread]
        public static void Main(string[] args)
        {
            string url = "http://127.0.0.1:11525";
            for (int i = 0; i < args.Length - 1; i++)
            {
                if (args[i] == "--url")
                {
                    url = args[i + 1];
                }
            }

            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new MainForm(url));
        }
    }
}
