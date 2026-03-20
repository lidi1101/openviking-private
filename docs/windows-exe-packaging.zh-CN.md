# Windows 鎵撳寘璇存槑

鑻辨枃鐗堬細`docs/windows-exe-packaging.md`

鏈枃妗ｈ鏄庡綋鍓?`ClawMemory.exe` 鐨?Windows 鎵撳寘缁撴瀯涓庝娇鐢ㄦ柟寮忋€?
## 1. 鎵撳寘鐩綍缁撴瀯

鐜板湪鎵€鏈夋墦鍖呯浉鍏宠剼鏈拰閰嶇疆闆嗕腑鍦細

- `pack\build_exe.ps1`
- `pack\package_release.ps1`
- `pack\packaging_config.ps1`
- `pack\ClawMemoryPack.spec`
- `pack\ov-binding-client.example.conf`

浠撳簱鏍圭洰褰曞彧淇濈暀鍙戝竷鍏ュ彛锛?
- `pack.ps1`
- `pack.bat`

鎵撳寘杈撳嚭缁熶竴鍐欏叆锛?
- `pack\dist\`

## 2. 褰撳墠鎵撳寘鐩爣

褰撳墠榛樿鍋囪濡備笅锛?
- 鍏ュ彛鏂囦欢锛歚openviking_cli/server_bootstrap.py`
- 鍖呭悕锛歚ClawMemory`
- AGFS 妯″紡锛歚binding-client`
- 鍖呬腑浼氬寘鍚?`FileProtectDriver`

## 3. 鎵撳寘鐜鍑嗗

### 3.1 Python

鑷冲皯瀹夎锛?
```powershell
pip install -U pyinstaller
pip install -U pybind11 setuptools wheel
```

鑴氭湰浼氭樉寮忔鏌ワ細

- `PyInstaller`
- `pybind11`
- `setuptools`
- `wheel`

鍙戝竷鏋勫缓寤鸿浼樺厛浣跨敤 Python 3.12銆侾ython 3.14 鐩墠浠嶄細瑙﹀彂 Pydantic V1 鍏煎鎬ц鍛婏紝鍙戝竷椋庨櫓杈冮珮銆?
### 3.2 Go

`libagfsbinding.dll` 閫氳繃 Go 鏋勫缓锛屽洜姝よ繕闇€瑕侊細

- `go`

### 3.3 C/C++ 宸ュ叿閾?
褰撳墠鏋勫缓閾捐矾渚濊禆 CMake + MinGW锛岄渶瑕侊細

- `cmake`
- `gcc`
- `g++`
- `mingw32-make`

鑴氭湰浼樺厛浣跨敤浠撳簱鍐呭伐鍏烽摼锛屾敮鎸佷互涓嬪舰寮忥細

- 宸茶В鍘嬬洰褰曪細`third_party\mingw64\`
- 鍒嗗嵎鍘嬬缉鍖呭叆鍙ｏ細`third_party\mingw64.7z.001`
- 鍘嬬缉鍖咃細`third_party\mingw64.7z`
- 鍘嬬缉鍖咃細`third_party\mingw64.zip`

濡傛灉鍙湁鍘嬬缉鍖咃紝鑴氭湰浼氬湪閲嶅缓杩愯鏃朵骇鐗╁墠鑷姩瑙ｅ帇銆?
### 3.4 杩愯閰嶇疆

褰撳墠閰嶇疆鏂囦欢鎸変互涓嬩紭鍏堢骇瑙ｆ瀽锛?
1. `OPENVIKING_CONFIG_FILE`
2. `%USERPROFILE%\.openviking\ov.conf`

骞惰姹傦細

```json
"storage": {
  "agfs": {
    "mode": "binding-client"
  }
}
```

鍦ㄦ牎楠屽墠锛宍pack\build_exe.ps1` 浼氱敤浠ヤ笅绀轰緥鏂囦欢鍚屾鐢ㄦ埛閰嶇疆锛?
- `pack\ov-binding-client.example.conf`

濡傛灉 `%USERPROFILE%\.openviking\` 鎴?`ov.conf` 涓嶅瓨鍦紝浼氳嚜鍔ㄥ垱寤猴紱濡傛灉宸插瓨鍦紝涔熶細琚ず渚嬫枃浠惰鐩栥€?
## 4. 鍛戒护浣跨敤

### 4.1 鏍圭洰褰曞叆鍙ｏ細`pack.ps1`

[`pack.ps1`](d:/HClawCode/LiDi/openviking-private/pack.ps1) 鏄牴鐩綍缁熶竴鍙戝竷鍏ュ彛锛屽畠鍐呴儴璋冪敤 [`pack/package_release.ps1`](d:/HClawCode/LiDi/openviking-private/pack/package_release.ps1)銆?
鍙敤鍛戒护濡備笅銆?
`.\pack.ps1`  
浣滅敤锛氭寜榛樿 `onefile` 妯″紡锛屽熀浜庣幇鏈夋瀯寤轰骇鐗╃敓鎴愬彂甯冨寘锛涘鏋滃凡鏈夊彲鐢ㄤ骇鐗╋紝灏变笉浼氬厛閲嶅缓銆?
`.\pack.ps1 -Mode onefile`  
浣滅敤锛氭樉寮忔寚瀹?`onefile` 妯″紡锛屾晥鏋滃拰榛樿鍛戒护涓€鑷淬€?
`.\pack.ps1 -rebuild`  
浣滅敤锛氬厛璋冪敤鍐呴儴鏋勫缓鑴氭湰閲嶆柊鏋勫缓 `ClawMemory.exe`锛屽啀鐢熸垚 `onefile` 鍙戝竷鍖呫€?
`.\pack.ps1 -Mode onefile -rebuild`  
浣滅敤锛氭樉寮忔寜 `onefile` 妯″紡鍏堥噸寤猴紝鍐嶇敓鎴愬崟鏂囦欢鍙戝竷鍖呫€?
`.\pack.ps1 -Mode onedir`  
浣滅敤锛氭寜 `onedir` 妯″紡锛屽熀浜庣幇鏈夌洰褰曠増鏋勫缓浜х墿鐢熸垚鍙戝竷鍖咃紱濡傛灉宸叉湁鍙敤 `onedir` 浜х墿锛屽氨涓嶄細鍏堥噸寤恒€?
`.\pack.ps1 -Mode onedir -rebuild`  
浣滅敤锛氬厛閲嶆柊鏋勫缓 `onedir` 鐗堟湰锛屽啀鐢熸垚鐩綍鐗堝彂甯冨寘銆?
瀵瑰簲鎵瑰鐞嗗叆鍙ｏ細

```bat
pack.bat
```

鎺ㄨ崘鐢ㄦ硶锛?
- 鏃ュ父鍙戝竷鍗曟枃浠跺寘锛歚.\pack.ps1 -rebuild`
- 闇€瑕佹洿绋崇殑鐩綍鐗堝彂甯冿細`.\pack.ps1 -Mode onedir -rebuild`

### 4.2 鍐呴儴鏋勫缓鑴氭湰锛歚pack\build_exe.ps1`

榛樿 `onefile` 鏋勫缓锛?
```powershell
.\pack.ps1
```

.\pack\build_exe.ps1
```

鏋勫缓 `onedir`锛?
```powershell
.\pack\build_exe.ps1 -Mode onedir
```

鍏堟竻鐞嗘棫杈撳嚭锛?
```powershell
.\pack\build_exe.ps1 -clean
```

寮哄埗閲嶅缓杩愯鏃朵骇鐗╁啀鏋勫缓锛?
```powershell
.\pack\build_exe.ps1 -clean -rebuild
```

鍏佽鍥為€€鍒?`pip install -e .`锛?
```powershell
.\pack\build_exe.ps1 -AutoInstall
```

`pack.ps1` 褰撳墠鍙毚闇诧細

- `-Mode onefile|onedir`
- `-rebuild`

瀹冩病鏈夊崟鐙毚闇?`-clean`銆傚洜涓烘牴鍏ュ彛瀹氫綅鏄€滃彂甯冨懡浠も€濓紝鏇寸粏鐨勬竻鐞嗗拰閲嶅缓鎺у埗鏀惧湪 `pack\build_exe.ps1`銆?
`pack\build_exe.ps1` 閲屾渶瀹规槗娣锋穯鐨勬槸 `-clean` 鍜?`-rebuild`锛?
- `-clean`锛氬彧娓呯悊鎵撳寘杈撳嚭鐩綍
- `-rebuild`锛氬己鍒堕噸寤鸿繍琛屾椂浜х墿

鍏蜂綋鏉ヨ锛?
- `-clean` 浼氬垹闄?`pack\build` 鍜?`pack\dist`
- `-clean` 涓嶄細涓诲姩鍒犻櫎 `openviking\lib\libagfsbinding.dll`
- 濡傛灉 `libagfsbinding.dll` 浠嶇劧瀛樺湪锛宍-clean` 鍚庝細鐩存帴澶嶇敤锛屼笉浼氶噸鏂版瀯寤?- `-rebuild` 浼氶澶栧垹闄?`openviking\lib\libagfsbinding.dll`
- 鍒犻櫎鍚庤剼鏈細閲嶆柊鏋勫缓 `libagfsbinding.dll`锛屽啀缁х画鎵撳寘

甯歌鍛戒护鍚箟锛?
```powershell
.\pack\build_exe.ps1 -clean
```

浣滅敤锛?
- 娓呯悊 `pack\build`
- 娓呯悊 `pack\dist`
- 閲嶆柊鎵撳寘
- 濡傛灉 `libagfsbinding.dll` 宸插瓨鍦紝鍒欑洿鎺ュ鐢?
```powershell
.\pack\build_exe.ps1 -clean -rebuild
```

浣滅敤锛?
- 娓呯悊 `pack\build`
- 娓呯悊 `pack\dist`
- 鍒犻櫎 `libagfsbinding.dll`
- 閲嶆柊鏋勫缓 `libagfsbinding.dll`
- 鍐嶉噸鏂版墦鍖?
### 4.3 鍐呴儴鍙戝竷鑴氭湰锛歚pack\package_release.ps1`

鍩轰簬鐜版湁鏋勫缓缁撴灉鐢熸垚鍙戝竷鍖咃細

```powershell
.\pack\package_release.ps1
```

鍏堥噸寤哄啀鎵撳彂甯冨寘锛?
```powershell
.\pack\package_release.ps1 -rebuild
```

鐢熸垚 `onedir` 鍙戝竷鍖咃細

```powershell
.\pack\package_release.ps1 -Mode onedir -rebuild
```

## 5. 杈撳嚭璺緞

`pack.ps1` / `pack\package_release.ps1` 鐩稿叧杈撳嚭濡備笅锛?
- `onefile`锛歚pack\dist\ClawMemory.exe`
- `onedir`锛歚pack\dist\ClawMemory\ClawMemory.exe`
- `pack\dist\release\ClawMemory\`
- `pack\dist\release\ClawMemory-onefile.zip`
- `pack\dist\release\ClawMemory-onedir.zip`

## 6. 鎵撳寘鏃堕渶瑕佹敞鎰忕殑闂

### 6.1 鍏堢湅宸ュ叿閾捐В鏋愮粨鏋?
`pack\build_exe.ps1` 鍚姩鏃朵細鎵撳嵃锛?
```text
Resolved toolchain:
  cmake -> ...
  gcc -> ...
  g++ -> ...
  mingw32-make -> ...
```

杩欓噷瑕佺‘璁ゅ綋鍓嶅懡涓殑鏄粨搴撳唴宸ュ叿閾撅紝杩樻槸璇敤浜嗙郴缁熼噷鏃х殑 `cmake/gcc/g++`銆?
### 6.2 褰╄壊姝ラ鎻愮ず

鑴氭湰浼氳緭鍑哄僵鑹叉楠ゆ彁绀猴細

- 闈掕壊锛氭楠ゅ紑濮?- 缁胯壊锛氭楠ゆ垚鍔?- 娲嬬孩锛氭楠ゅけ璐?
鑴氭湰缁撴潫鏃惰繕浼氭寜鎵ц椤哄簭杈撳嚭甯︾紪鍙风殑姝ラ姹囨€汇€?
### 6.3 `onefile` 鍜?`onedir`

`onefile`锛?
- 鍙敓鎴愪竴涓?`exe`
- 鍒嗗彂鏇存柟渚?- 杩愯鏃朵細鍏堣В鍖呭埌涓存椂鐩綍

`onedir`锛?
- 鐢熸垚鐩綍缁撴瀯
- 鏇翠究浜庢帓鏌ラ棶棰?- 鍙戝竷鏃惰鏁寸洰褰曚竴璧蜂氦浠?
### 6.4 `FileProtectDriver`

褰撳墠绋嬪簭杩愯鏃朵細鑷姩璋冪敤锛?
- 鍚姩鍓嶏細`FileProtectDriver\FilterUpdate.cmd`
- 閫€鍑烘椂锛歚FileProtectDriver\FilterUninstall.cmd`

鎵€浠ュ彂甯冧骇鐗╀腑蹇呴』鍖呭惈 `FileProtectDriver`锛岃€屼笖鐩爣鏈哄櫒涓婂彲鑳介渶瑕佺鐞嗗憳鏉冮檺銆?
### 6.5 绂荤嚎鎵撳寘

绂荤嚎鐜涓嬭鎻愬墠纭锛?
- Python 渚濊禆宸插畨瑁?- `go` 鍙敤
- `PyInstaller` 鍙敤
- `openviking\_version.py` 瀛樺湪
- `third_party\mingw64\` 鎴栧叾鍘嬬缉鍖呭瓨鍦?
鏈€閫傚悎楠岃瘉绂荤嚎閾捐矾鐨勫懡浠ゆ槸锛?
```powershell
.\pack\build_exe.ps1 -clean -rebuild
```

濡傛灉浣犲彧鏄兂娓呮帀鏃х殑鎵撳寘缁撴灉锛屼絾淇濈暀鐜版垚鐨?`libagfsbinding.dll`锛屽垯鐢細

```powershell
.\pack\build_exe.ps1 -clean
```

### 6.6 鍒嗗嵎鍘嬬缉鍖?
浠ヤ笅鍒嗗嵎鏍煎紡宸叉敮鎸侊細

- `third_party\mingw64.7z.001`
- `third_party\mingw64.7z.002`
- `third_party\mingw64.7z.003`

鑴氭湰浼氭妸 `.001` 瑙嗕负鍏ュ彛鏂囦欢銆?
## 7. 鐩稿叧鏂囦欢

- `pack.ps1`
- `pack.bat`
- `pack\build_exe.ps1`
- `pack\package_release.ps1`
- `pack\packaging_config.ps1`
- `pack\ClawMemoryPack.spec`
- `pack\ov-binding-client.example.conf`

