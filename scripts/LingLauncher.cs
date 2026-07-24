using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Threading;
using System.Windows.Forms;

namespace LingLauncher
{
    internal static class Program
    {
        private const string ProjectRoot = @"E:\澪\project-mnemosyne";
        private const string VoiceRoot = @"E:\澪\ling-local-voice";
        private const string LingUrl = "http://127.0.0.1:8001";
        private const string VoiceUrl = "http://127.0.0.1:9881/api/health";

        [STAThread]
        private static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new LauncherForm());
        }

        private sealed class LauncherForm : Form
        {
            private readonly Label status;
            private readonly Button start;
            private readonly Button open;
            private readonly Button stop;

            public LauncherForm()
            {
                Text = "LING 启动器";
                ClientSize = new Size(440, 245);
                FormBorderStyle = FormBorderStyle.FixedDialog;
                MaximizeBox = false;
                StartPosition = FormStartPosition.CenterScreen;
                Font = new Font("Microsoft YaHei UI", 10F);

                var title = new Label
                {
                    Text = "LING 本地启动器",
                    Location = new Point(22, 18),
                    Size = new Size(390, 31),
                    Font = new Font("Microsoft YaHei UI", 16F, FontStyle.Bold)
                };
                var note = new Label
                {
                    Text = "会检查并启动 LING 与本地 mio 声音服务。EasyVtuber 保持独立。",
                    Location = new Point(24, 58),
                    Size = new Size(390, 44),
                    ForeColor = Color.FromArgb(75, 91, 115)
                };

                start = MakeButton("启动 LING（含本地声音）", 24, 114, 255);
                start.Click += delegate { StartLing(); };
                open = MakeButton("打开网页", 292, 114, 122);
                open.Click += delegate { OpenBrowser(); };
                stop = MakeButton("停止 LING", 24, 166, 122);
                stop.Click += delegate { StopLing(); };
                var quit = MakeButton("关闭启动器", 158, 166, 122);
                quit.Click += delegate { Close(); };

                status = new Label
                {
                    Text = GetStatus(),
                    Location = new Point(24, 215),
                    Size = new Size(390, 24),
                    ForeColor = Color.FromArgb(55, 112, 78)
                };
                Controls.AddRange(new Control[] { title, note, start, open, stop, quit, status });
            }

            private static Button MakeButton(string text, int x, int y, int width)
            {
                return new Button { Text = text, Location = new Point(x, y), Size = new Size(width, 39), FlatStyle = FlatStyle.System };
            }

            private void StartLing()
            {
                if (!Directory.Exists(ProjectRoot) || !Directory.Exists(VoiceRoot))
                {
                    MessageBox.Show("找不到 LING 或本地声音目录。\n\n需要：\n" + ProjectRoot + "\n" + VoiceRoot, "LING 启动器", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return;
                }
                ToggleControls(false);
                try
                {
                    if (!Healthy(VoiceUrl))
                    {
                        status.Text = "正在启动本地 mio 声音服务…";
                        Application.DoEvents();
                        RunPowerShell(Path.Combine(VoiceRoot, "scripts", "start-local-voice.ps1"), false);
                        if (!WaitForHealth(VoiceUrl, 45)) throw new Exception("本地声音服务未在 45 秒内就绪。");
                    }
                    if (!Healthy(LingUrl + "/api/health"))
                    {
                        status.Text = "正在启动 LING…";
                        Application.DoEvents();
                        RunPowerShell(Path.Combine(ProjectRoot, "scripts", "start_local_server.ps1"), true);
                        if (!WaitForHealth(LingUrl + "/api/health", 35)) throw new Exception("LING 未在 35 秒内就绪。");
                    }
                    status.Text = "LING 与 mio 已就绪，正在打开网页。";
                    OpenBrowser();
                }
                catch (Exception error)
                {
                    status.Text = "启动失败。";
                    MessageBox.Show(error.Message + "\n\n可查看：\n" + Path.Combine(ProjectRoot, "logs"), "LING 启动器", MessageBoxButtons.OK, MessageBoxIcon.Error);
                }
                finally { ToggleControls(true); }
            }

            private void StopLing()
            {
                try
                {
                    RunPowerShell(Path.Combine(ProjectRoot, "scripts", "stop_local_server.ps1"), false);
                    status.Text = "已请求停止 LING。本地声音服务保留运行，便于下次更快启动。";
                }
                catch (Exception error)
                {
                    MessageBox.Show(error.Message, "LING 启动器", MessageBoxButtons.OK, MessageBoxIcon.Error);
                }
            }

            private static void OpenBrowser()
            {
                Process.Start(new ProcessStartInfo(LingUrl) { UseShellExecute = true });
            }

            private static void RunPowerShell(string scriptPath, bool openBrowser)
            {
                if (!File.Exists(scriptPath)) throw new FileNotFoundException("启动脚本不存在。", scriptPath);
                string arguments = "-NoProfile -ExecutionPolicy Bypass -File \"" + scriptPath + "\"";
                if (openBrowser) arguments += " -OpenBrowser";
                var info = new ProcessStartInfo("powershell.exe", arguments)
                {
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    WindowStyle = ProcessWindowStyle.Hidden,
                    WorkingDirectory = Path.GetDirectoryName(scriptPath)
                };
                Process.Start(info);
            }

            private static bool Healthy(string url)
            {
                try
                {
                    var request = (HttpWebRequest)WebRequest.Create(url);
                    request.Timeout = 1200;
                    request.ReadWriteTimeout = 1200;
                    using (var response = (HttpWebResponse)request.GetResponse()) return response.StatusCode == HttpStatusCode.OK;
                }
                catch { return false; }
            }

            private static bool WaitForHealth(string url, int seconds)
            {
                for (var attempt = 0; attempt < seconds * 2; attempt++)
                {
                    if (Healthy(url)) return true;
                    Application.DoEvents();
                    Thread.Sleep(500);
                }
                return false;
            }

            private string GetStatus()
            {
                return Healthy(LingUrl + "/api/health") ? "LING 正在运行。" : "LING 当前未启动。";
            }

            private void ToggleControls(bool enabled)
            {
                start.Enabled = enabled;
                open.Enabled = enabled;
                stop.Enabled = enabled;
            }
        }
    }
}
