; CCD Train 缺陷检测训练平台 - 安装程序脚本
; 编译：ISCC.exe installer.iss
; 依赖：backend\dist\CCDTrain\（PyInstaller 产物）

#define MyAppName "CCD Train"
#define MyAppVersion "0.2.0"
#define MyAppExeName "CCDTrain.exe"

[Setup]
AppId={{D1F4A9C2-7E3B-4C6D-9A5F-2B8E1C4D6A70}
AppName={#MyAppName} 缺陷检测训练平台
AppVersion={#MyAppVersion}
AppPublisher=CCD Train
DefaultDirName={localappdata}\Programs\CCDTrain
DefaultGroupName=CCD Train
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist_installer
OutputBaseFilename=CCDTrain-Setup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=no
; 磁盘提示
DiskSpanning=no
; 版本信息
VersionInfoVersion={#MyAppVersion}
VersionInfoProductName=CCD Train

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："

[Files]
Source: "..\dist\CCDTrain\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\CCD Train"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\CCD Train"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 CCD Train"; Flags: nowait postinstall skipifsilent

[Code]
{ 卸载前提示：数据目录随应用目录，直接删除 }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    if MsgBox('是否同时删除训练数据（数据库/训练产物/标注）？' + #13#10 +
      '删除后不可恢复。', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    begin
      DelTree(ExpandConstant('{app}\data'), True, True, True);
    end;
  end;
end;
