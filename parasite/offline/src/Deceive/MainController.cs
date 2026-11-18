using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net.Security;
using System.Net.Sockets;
using System.Security.Cryptography.X509Certificates;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using System.Xml;
using System.Xml.Linq;
using Deceive.Properties;

namespace Deceive;

internal class MainController : ApplicationContext
{
    internal MainController()
    {
        TrayIcon = new NotifyIcon
        {
            Icon = Resources.DeceiveIcon,
            Visible = false,
            BalloonTipTitle = StartupHandler.DeceiveTitle,
            BalloonTipText = "Parasite is currently masking your status. Right-click the tray icon for more options."
        };

        LoadStatus();
        UpdateTray();
    }

    private NotifyIcon TrayIcon { get; }
    public bool Enabled { get; set; } = true;
    public string Status { get; set; } = null!;
    private string StatusFile { get; } = Path.Combine(Persistence.DataDir, "status");
    public bool ConnectToMuc { get; set; } = true;
    private bool SentIntroductionText { get; set; } = false;
    private CancellationTokenSource? ShutdownToken { get; set; } = null;

    private ToolStripMenuItem EnabledMenuItem { get; set; } = null!;
    private ToolStripMenuItem ChatStatus { get; set; } = null!;
    private ToolStripMenuItem OfflineStatus { get; set; } = null!;
    private ToolStripMenuItem MobileStatus { get; set; } = null!;

    private List<ProxiedConnection> Connections { get; } = new();

    public void StartServingClients(TcpListener server, X509Certificate2 serverCert, string chatHost, int chatPort)
    {
        Task.Run(() => ServeClientsAsync(server, serverCert, chatHost, chatPort));
    }

    private async Task ServeClientsAsync(TcpListener server, X509Certificate2 serverCert, string chatHost, int chatPort)
    {
        while (true)
        {
            try
            {
                // no need to shutdown, we received a new request
                ShutdownToken?.Cancel();
                ShutdownToken = null;

                var incoming = await server.AcceptTcpClientAsync();
                var sslIncoming = new SslStream(incoming.GetStream());
                await sslIncoming.AuthenticateAsServerAsync(serverCert);

                TcpClient outgoing;
                while (true)
                {
                    try
                    {
                        outgoing = new TcpClient(chatHost, chatPort);
                        break;
                    }
                    catch (SocketException e)
                    {
                        Trace.WriteLine(e);
                        var result = MessageBox.Show(
                            "Sohbet sunucusuna bağlanılamadı. İnternet bağlantını kontrol et. " +
                            "Sorun sürerse ve Parasite Offline olmadan sohbete normal bağlanabiliyorsan, " +
                            "lütfen GitHub'da bildir (https://github.com/lustmyself/Parasite/issues).",
                            StartupHandler.DeceiveTitle,
                            MessageBoxButtons.RetryCancel,
                            MessageBoxIcon.Error,
                            MessageBoxDefaultButton.Button1
                        );
                        if (result == DialogResult.Cancel)
                            Environment.Exit(0);
                    }
                }

                var sslOutgoing = new SslStream(outgoing.GetStream());
                await sslOutgoing.AuthenticateAsClientAsync(chatHost);

                var proxiedConnection = new ProxiedConnection(this, sslIncoming, sslOutgoing);
                proxiedConnection.Start();
                proxiedConnection.ConnectionErrored += (_, _) =>
                {
                    Trace.WriteLine("Disconnected incoming connection.");
                    Connections.Remove(proxiedConnection);

                    if (Connections.Count == 0)
                    {
                        Task.Run(ShutdownIfNoReconnect);
                    }
                };
                Connections.Add(proxiedConnection);

                if (false)
                {
                    SentIntroductionText = true;
                    _ = Task.Run(async () =>
                    {
                        await Task.Delay(10_000);
                        await SendIntroductionTextAsync();
                    });
                }
            } catch (Exception e)
            {
                Trace.WriteLine("Failed to handle incoming connection.");
                Trace.WriteLine(e);
            }
        }
    }

    private void UpdateTray()
    {
        var aboutMenuItem = new ToolStripMenuItem(StartupHandler.DeceiveTitle) { Enabled = false };

        EnabledMenuItem = new ToolStripMenuItem("Enabled", null, async (_, _) =>
        {
            Enabled = !Enabled;
            await UpdateStatusAsync(Enabled ? Status : "chat");
            await SendMessageFromFakePlayerAsync(Enabled ? "Parasite Offline açıldı." : "Parasite Offline kapatıldı.");
            UpdateTray();
        })
        { Checked = Enabled };

        var mucMenuItem = new ToolStripMenuItem("Enable lobby chat", null, (_, _) =>
        {
            ConnectToMuc = !ConnectToMuc;
            UpdateTray();
        })
        { Checked = ConnectToMuc };

        ChatStatus = new ToolStripMenuItem("Online", null, async (_, _) =>
        {
            await UpdateStatusAsync(Status = "chat");
            Enabled = true;
            UpdateTray();
        })
        { Checked = Status.Equals("chat") };

        OfflineStatus = new ToolStripMenuItem("Offline", null, async (_, _) =>
        {
            await UpdateStatusAsync(Status = "offline");
            Enabled = true;
            UpdateTray();
        })
        { Checked = Status.Equals("offline") };

        MobileStatus = new ToolStripMenuItem("Mobile", null, async (_, _) =>
        {
            await UpdateStatusAsync(Status = "mobile");
            Enabled = true;
            UpdateTray();
        })
        { Checked = Status.Equals("mobile") };

        var typeMenuItem = new ToolStripMenuItem("Status Type", null, ChatStatus, OfflineStatus, MobileStatus);
        
        var currentStartup = Persistence.GetStartupStatus();
        var startupOnline = new ToolStripMenuItem("Online", null, (_, _) =>
        {
            Persistence.SetStartupStatus("chat");
            UpdateTray();
        })
        { Checked = currentStartup == "chat" };

        var startupOffline = new ToolStripMenuItem("Offline", null, (_, _) =>
        {
            Persistence.SetStartupStatus("offline");
            UpdateTray();
        })
        { Checked = currentStartup == "offline" };

        var startupMobile = new ToolStripMenuItem("Mobile", null, (_, _) =>
        {
            Persistence.SetStartupStatus("mobile");
            UpdateTray();
        })
        { Checked = currentStartup == "mobile" };

        var startupLast = new ToolStripMenuItem("Remember Last", null, (_, _) =>
        {
            Persistence.SetStartupStatus("last");
            UpdateTray();
        })
        { Checked = currentStartup == "last" };

        var startupStatusMenuItem = new ToolStripMenuItem("Default Status on Startup", null, startupOnline, startupOffline, startupMobile, startupLast);

        var restartWithDifferentGameItem = new ToolStripMenuItem("Restart and launch a different game", null, (_, _) =>
        {
            var result = MessageBox.Show(
                "Restart Parasite to launch a different game? This will also stop related games if they are running.",
                StartupHandler.DeceiveTitle,
                MessageBoxButtons.YesNo,
                MessageBoxIcon.Question,
                MessageBoxDefaultButton.Button1
            );

            if (result is not DialogResult.Yes)
                return;

            Utils.KillProcesses();
            Thread.Sleep(2000);

            Persistence.SetDefaultLaunchGame(LaunchGame.Prompt);
            Process.Start(Application.ExecutablePath);
            Environment.Exit(0);
        });

        var quitMenuItem = new ToolStripMenuItem("Quit", null, (_, _) =>
        {
            var result = MessageBox.Show(
                "Are you sure you want to stop Parasite? This will also stop related games if they are running.",
                StartupHandler.DeceiveTitle,
                MessageBoxButtons.YesNo,
                MessageBoxIcon.Question,
                MessageBoxDefaultButton.Button1
            );

            if (result is not DialogResult.Yes)
                return;

            Utils.KillProcesses();
            SaveStatus();
            Application.Exit();
        });

        TrayIcon.ContextMenuStrip = new ContextMenuStrip();

#if DEBUG
        var sendTestMsg = new ToolStripMenuItem("Send message", null, async (_, _) => { await SendMessageFromFakePlayerAsync("Test"); });

        TrayIcon.ContextMenuStrip.Items.AddRange(new ToolStripItem[]
        {
            aboutMenuItem, EnabledMenuItem, typeMenuItem, startupStatusMenuItem, mucMenuItem, sendTestMsg, restartWithDifferentGameItem, quitMenuItem
        });
#else
        TrayIcon.ContextMenuStrip.Items.AddRange(new ToolStripItem[] { aboutMenuItem, EnabledMenuItem, typeMenuItem, startupStatusMenuItem, mucMenuItem, restartWithDifferentGameItem, quitMenuItem });
#endif
    }

    public async Task HandleChatMessage(string content)
    {
        if (content.ToLower().Contains("offline"))
        {
            if (!Enabled)
                await SendMessageFromFakePlayerAsync("Parasite Offline açıldı.");
            OfflineStatus.PerformClick();
        }
        else if (content.ToLower().Contains("mobile"))
        {
            if (!Enabled)
                await SendMessageFromFakePlayerAsync("Parasite Offline açıldı.");
            MobileStatus.PerformClick();
        }
        else if (content.ToLower().Contains("online"))
        {
            if (!Enabled)
                await SendMessageFromFakePlayerAsync("Parasite Offline açıldı.");
            ChatStatus.PerformClick();
        }
        else if (content.ToLower().Contains("enable"))
        {
            if (Enabled)
                await SendMessageFromFakePlayerAsync("Parasite Offline zaten açık.");
            else
                EnabledMenuItem.PerformClick();
        }
        else if (content.ToLower().Contains("disable"))
        {
            if (!Enabled)
                await SendMessageFromFakePlayerAsync("Parasite Offline zaten kapalı.");
            else
                EnabledMenuItem.PerformClick();
        }
        else if (content.ToLower().Contains("status"))
        {
            if (Status == "chat")
                await SendMessageFromFakePlayerAsync("Çevrimiçi görünüyorsun.");
            else
                await SendMessageFromFakePlayerAsync((Status == "mobile" ? "Mobilde" : "Çevrimdışı") + " görünüyorsun.");
        }
        else if (content.ToLower().Contains("help"))
        {
            await SendMessageFromFakePlayerAsync("Parasite Offline'ı hızlıca ayarlamak için şu mesajları gönderebilirsin: online/offline/mobile/enable/disable/status");
        }
    }

    private async Task SendIntroductionTextAsync()
    {
        Persistence.SetHasShownIntroduction();
        await SendMessageFromFakePlayerAsync("Welcome! Parasite is running and you are currently appearing " + Status +
                                             ". Despite what the game client may indicate, you are appearing offline to your friends unless you manually disable Parasite.");
        await Task.Delay(200);
        await SendMessageFromFakePlayerAsync(
            "If you want to invite others while being offline, you may need to disable Parasite for them to accept. You can enable Parasite again as soon as they are in your lobby.");
        await Task.Delay(200);
        await SendMessageFromFakePlayerAsync("To enable or disable Parasite, or to configure other settings, find Parasite in your tray icons.");
        await Task.Delay(200);
        await SendMessageFromFakePlayerAsync("Have fun!");
    }

    private async Task SendMessageFromFakePlayerAsync(string message)
    {
        foreach (var connection in Connections)
            await connection.SendMessageFromFakePlayerAsync(message);
    }

    private async Task UpdateStatusAsync(string newStatus)
    {
        try { File.WriteAllText(StatusFile, newStatus); } catch (IOException) { }
        foreach (var connection in Connections)
            await connection.UpdateStatusAsync(newStatus);

        if (newStatus == "chat")
            await SendMessageFromFakePlayerAsync("Artık çevrimiçi görünüyorsun.");
        else
            await SendMessageFromFakePlayerAsync("Artık " + (newStatus == "mobile" ? "mobilde" : "çevrimdışı") + " görünüyorsun.");
    }

    private void LoadStatus()
    {
        var startupStatus = Persistence.GetStartupStatus();

        if (startupStatus is "chat" or "offline" or "mobile")
        {
            Status = startupStatus;
            return;
        }

        if (!File.Exists(StatusFile))
        {
            Status = "offline";
            return;
        }

        // "last" or unrecognized: use the saved session status.
        var saved = File.ReadAllText(StatusFile);
        Status = saved switch
        {
            "chat" => "chat",
            "mobile" => "mobile",
            _ => "offline"
        };
    }

    private async Task ShutdownIfNoReconnect()
    {
        if (ShutdownToken == null)
            ShutdownToken = new CancellationTokenSource();
        await Task.Delay(60_000, ShutdownToken.Token);

        Trace.WriteLine("Received no new connections after 60s, shutting down.");
        Environment.Exit(0);
    }

    private void SaveStatus() => File.WriteAllText(StatusFile, Status);
}
