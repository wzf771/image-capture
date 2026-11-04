; Image capture 安装包（Inno Setup 6）
; 编译：ISCC.exe /DMyAppVersion=1.0.0 ImageCapture.iss
; 设计要点：
;   · 装到 %LOCALAPPDATA%\Programs\ImageCapture —— 免管理员、目录可写
;     （程序会在自己旁边写 config / cache / output / logs）
;   · 从开始菜单和桌面都能启动，带卸载项
;   · UI 文案用中文（Default.isl 的关键条目覆盖）

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

#define MyAppName "Image capture"
#define MyAppNameCn "显微图像统一视野裁剪"
#define MyAppExeName "ImageCapture.exe"
#define MyAppPublisher "王卓"
#define MyAppUrl "https://github.com/"

[Setup]
AppId={{7C4E1B52-9A3D-4C2E-9E77-2B1F5D8A6C34}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppUrl}
AppSupportURL={#MyAppUrl}
AppUpdatesURL={#MyAppUrl}
VersionInfoVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\ImageCapture
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=installer
OutputBaseFilename=ImageCapture_Setup_{#MyAppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableWelcomePage=no
LicenseFile=..\LICENSE

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[Messages]
; —— 关键界面汉化（其余保留英文默认）——
WelcomeLabel1=欢迎安装 [name]
WelcomeLabel2=即将在你的电脑上安装 [name/ver]。%n%n这是{#MyAppNameCn}工具：把不同倍数、不同视野的显微照片，裁成统一视野、统一尺寸、带标尺的成品图。%n%n继续请点「下一步」。
SelectDirDesc=要把 [name] 装到哪个文件夹？
SelectDirLabel3=安装程序会把 [name] 放到下面的文件夹。
SelectDirBrowseLabel=点「浏览」可以换一个位置，点「下一步」继续。
ReadyLabel1=现在开始安装 [name]。
ReadyLabel2a=点「安装」开始；想改设置就点「上一步」。
ReadyLabel2b=点「安装」开始安装。
InstallingLabel=正在把文件复制到你的电脑，请稍候…
FinishedHeadingLabel=[name] 安装完成
FinishedLabel=点「完成」关闭安装程序。开始菜单和桌面上都有 {#MyAppName} 的快捷方式。
ClickNext=下一步(&N) >
ClickInstall=安装(&I)
ClickFinish=完成(&F)
ButtonNext=下一步(&N) >
ButtonBack=< 上一步(&B)
ButtonInstall=安装(&I)
ButtonFinish=完成(&F)
ButtonCancel=取消(&C)
ExitSetupTitle=退出安装
ExitSetupMessage=还没装完，确定要退出吗？
ConfirmUninstall=确定要卸载 %1 吗？
UninstalledAll=%1 已经卸载干净。
UninstalledMost=%1 卸载完成。%n%n有少数文件没删掉，可以手动删除。
StatusUninstalling=正在卸载 %1…
CreateDesktopIcon=创建桌面快捷方式(&D)
[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\ImageCapture\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
Name: "{app}\config"
Name: "{app}\cache"
Name: "{app}\output"
Name: "{app}\logs"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\icon.ico"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\cache"
Type: filesandordirs; Name: "{app}\logs"
