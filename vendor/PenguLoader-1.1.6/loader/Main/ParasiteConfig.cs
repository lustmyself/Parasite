using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;

namespace PenguLoader.Main
{
    // Parasite-only adapter: the loader remains official, but Parasite needs the core
    // activation state mirrored into its existing cf.ini.
    internal static class ParasiteConfig
    {
        // Parasite passes its cf.ini: the desktop user's, which core.dll reads in
        // the League client. This process runs elevated, and when Parasite was
        // elevated with another account, LocalApplicationData is that account's.
        private static string ConfigPath
        {
            get
            {
                var fromParasite = Environment.GetEnvironmentVariable("PARASITE_CONFIG_PATH");
                if (!string.IsNullOrWhiteSpace(fromParasite))
                    return fromParasite;

                return Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "Parasite",
                    "cf.ini");
            }
        }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool WritePrivateProfileString(
            string section,
            string key,
            string value,
            string filePath);

        public static void SetLoaderState(bool active)
        {
            var directory = Path.GetDirectoryName(ConfigPath);
            if (!Directory.Exists(directory))
                Directory.CreateDirectory(directory);

            var loaderPath = active
                ? AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
                : string.Empty;

            if (!WritePrivateProfileString("General", "disabled", active ? "0" : "1", ConfigPath) ||
                !WritePrivateProfileString("General", "loaderpath", loaderPath, ConfigPath))
            {
                throw new Win32Exception(Marshal.GetLastWin32Error(), "Could not update Parasite cf.ini.");
            }
        }
    }
}
