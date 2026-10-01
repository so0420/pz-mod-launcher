# PZ Mod Launcher

Project Zomboid Windows 클라이언트를 위한 간단한 공용 런처입니다. 특정 서버의 이미지·주소·계정·패치는 포함하지 않습니다.

- 기본 설정으로 일반 게임 실행
- 서버 주소를 지정하면 일회성 자동 접속
- 모드팩 URL을 지정하면 전체 설치·증분 업데이트·ZIP 수동 설치
- 선택한 Java agent JAR와 옵션을 게임 실행 시 적용
- 워크샵 캐시 강제 삭제 옵션 (기본 꺼짐, 삭제 전 확인)
- 모드팩 ID별 설치 기록, 개인 모드·세이브 보존, 설치 실패 시 복원
- 서버측 모드 변경 자동 감지·패키지 생성·최신 파일 HTTP 서빙

Windows 10/11, Steam판 64비트 클라이언트용입니다. 자동 접속 Lua는 Build 42 API를 기준으로 작성했습니다. 실제 게임 버전에 따라 자동 접속과 패치 호환성은 확인해야 합니다. Java 패치는 선택 사항이며 런처가 자동으로 다운로드하거나 게임 설정 파일에 등록하지 않습니다.

## 바로 빌드하기

Python 3.11 이상을 설치할 때 **Tcl/Tk**와 **Python Launcher 또는 PATH 등록**을 포함해주세요. 개발 및 EXE 빌드는 Python 3.12에서 확인했습니다.

`build.bat`을 더블클릭하면 가상환경 생성, 빌드 도구 설치, 테스트, EXE 빌드를 차례로 실행합니다.

```bat
build.bat
```

결과는 `dist\PZModLauncher.exe`입니다. EXE 사용자에게는 Python 설치가 필요 없습니다. 런처 실행에 필요한 기본 설정과 자동 접속 Lua가 EXE에 포함됩니다.

서버용 런처는 빌드 설정 예제를 복사한 뒤 주소와 서버 입장 비밀번호를 넣어 빌드합니다.

```bat
copy launcher-build.example.json launcher-build.json
build.bat
```

`launcher-build.json`이 있으면 `build.bat`이 자동으로 읽어 EXE에 포함합니다. `server_password`에는 공통 서버 입장 비밀번호를 넣고, 비밀번호가 없는 서버는 빈 문자열로 둡니다. 게임 유저명과 개인 계정 비밀번호는 빌드에 넣지 않습니다. 빌드 설정은 Git에서 제외되며, 공개 예제에는 실제 주소와 비밀번호를 넣지 마세요. 다른 설정 파일을 사용할 때는 `--config 파일경로`를 지정할 수 있습니다.

패치 JAR를 런처에 넣고 빌드하려면 다음과 같이 실행합니다. `patches` 폴더와 JAR는 Git에서 제외됩니다.

```bat
build.bat --java-agent "patches\custom-agent.jar"
build.bat --config launcher-build.json --java-agent "patches\custom-agent.jar" --agent-options "debug=true"
```

JAR를 EXE에 포함하고 해당 패치를 적용하는 기본 설정을 함께 넣습니다. 옵션이 필요 없으면 `--agent-options`를 생략하세요. JAR는 게임이 사용하는 Java 버전 및 게임 빌드와 호환되는 **Java agent**여야 합니다. 일반 모드 JAR 또는 의존 라이브러리를 지정하는 기능은 아닙니다.

패치를 넣은 EXE는 실행 시 JAR를 `%USERPROFILE%\Zomboid\launchers\runtime`에 해시별로 보관합니다. 게임 실행 중 런처를 닫아도 패치 파일은 유지됩니다. 기본 빌드에는 JAR가 없으며, 저장소에도 패치 바이너리를 포함하지 않습니다.

GitHub Actions도 푸시 및 수동 실행 시 테스트 후 Windows EXE를 만들어 `PZModLauncher-Windows` 아티팩트로 제공합니다.

## 런처 설정

실행 화면의 **설정**에서 이름, 모드팩 ID, 배포 URL, 게임 서버 주소, 게임 폴더, Java 패치, 워크샵 강제 삭제 여부를 바꿀 수 있습니다. 저장한 `launcher-config.json`은 EXE 옆에 생성되며 EXE에 포함된 기본 설정보다 우선합니다. 쓰기 가능한 폴더에서 실행해주세요.

아래는 서버용 빌드 설정 **`launcher-build.json`** 예시입니다. `server_password`를 서버 입장 비밀번호로 바꾼 뒤 `build.bat`을 실행하면 EXE에 포함됩니다. 비밀번호가 없는 서버는 빈 문자열(`""`)로 두세요. 게임 계정명과 개인 계정 비밀번호는 실행할 때 사용자가 입력합니다.

```json
{
  "title": "PZ Mod Launcher",
  "pack_id": "my-server",
  "modpack_url": "https://example.com/modpack",
  "server_host": "play.example.com",
  "server_port": "16261",
  "server_password": "example-server-password",
  "force_workshop_delete": false,
  "game_path": "",
  "java_agent": "",
  "java_agent_options": ""
}
```

| 설정 | 사용 방법 |
| --- | --- |
| `title` | 창과 화면에 표시할 이름 |
| `pack_id` | 서버별 고유 ID. 영문·숫자·밑줄·하이픈, 최대 48자 |
| `modpack_url` | `manifest.json`과 `mods.zip`이 있는 배포 폴더 URL. 비우면 업데이트 없이 실행 |
| `server_host`, `server_port` | 게임 서버 호스트명 또는 IPv4 주소와 포트. 호스트를 비우면 일반 실행 |
| `server_password` | 공통 서버 입장 비밀번호. 빌드 설정에서 지정해 EXE에 포함하며, 실행 화면에서 입력받지 않음. 비밀번호가 없으면 빈 문자열 |
| `force_workshop_delete` | `true`이면 실행·모드 설치 전에 좀보이드 워크샵 캐시 삭제를 확인. 기본값 `false` |
| `game_path` | `ProjectZomboid64.json`이 있는 게임 폴더. 비우면 Steam 라이브러리에서 탐색 |
| `java_agent` | 선택한 패치 JAR. 절대 경로 또는 상대 경로 |
| `java_agent_options` | JVM의 `-javaagent:JAR=옵션`에 전달할 문자열 |

상대 JAR 경로는 **게임 폴더 → EXE 폴더 → EXE에 포함된 파일** 순서로 찾습니다. `--java-agent` 빌드는 `patches/파일명.jar`를 기본 경로로 지정합니다. 패치를 끄려면 JAR 경로와 옵션을 둘 다 비우세요. 게임의 `ProjectZomboid64.json`에 이미 등록된 JVM 옵션과 Java agent는 유지하며, 같은 JAR를 런처에서 명시하면 해당 agent의 옵션만 대체합니다. 기존 게임 설정에 등록된 패치를 해제하는 작업은 게임 설정에서 직접 해야 합니다.

`PZ_MODPACK_URL` 환경변수는 시작할 때 배포 URL을 덮어쓸 수 있습니다. 다른 서버로 바꿀 때는 `pack_id`도 별도로 지정해주세요. 각 서버의 기록은 `%USERPROFILE%\Zomboid\launchers\pack-<ID>`에 저장합니다. 서로 다른 모드팩이라도 같은 이름의 모드 폴더를 동시에 관리하지 않으며, 충돌하면 기존 폴더를 보존하고 설치를 중단합니다. 서버를 바꿀 때 충돌하는 기존 모드팩은 먼저 제거해주세요.

게임 실행 로그는 해당 기록 폴더의 `pz-launcher.log`에서 확인합니다. 게임은 번들 Java로 실행하며, Steam은 미리 실행해두세요.

방송 중 주소 노출을 줄이기 위해 접속 화면에는 서버 주소를 표시하지 않습니다. 설정의 모드팩 URL·서버 주소·포트도 기본적으로 가리고 **주소 표시**를 선택할 때만 보여줍니다. 런처 진행 내역과 오류 팝업에서도 설정된 서버 주소와 배포 URL을 가립니다. 설정 JSON, 게임 화면, 별도로 여는 게임 로그의 표시 방식은 이 기능의 대상이 아닙니다.

## 워크샵 강제 삭제 옵션

설정의 **워크샵 강제 삭제**를 켜거나 빌드 설정에 `"force_workshop_delete": true`를 넣으면 사용할 수 있습니다. 기본값은 `false`입니다. 게임 실행, 모드 업데이트, 모드팩 재설치, ZIP 수동 설치를 시작할 때 적용하며, 런처를 열거나 설정을 저장하는 것만으로 삭제하지 않습니다.

탐색한 **각 Steam 라이브러리의 `steamapps/workshop/content/108600` 폴더 전체**가 삭제 대상입니다. 삭제할 경로와 모드 개수를 확인 창에 표시하며, 취소하면 해당 실행·설치 작업도 중단합니다. 다른 게임의 워크샵 파일, `%USERPROFILE%\Zomboid\mods`의 로컬 모드, 세이브, 게임 본체는 삭제하지 않습니다. **이 모드팩 제거** 버튼은 이 옵션과 관계없이 로컬 모드팩만 제거합니다.

게임이 종료된 상태에서만 삭제하며, 읽기 전용 파일은 해제를 시도합니다. 파일 잠금·권한 오류 등으로 삭제에 실패하면 작업을 중단합니다. 연결된 폴더·파일(심볼릭 링크·정션 등)이 포함된 캐시는 삭제하지 않습니다. 게임 폴더를 직접 지정했더라도 이 옵션을 켜면 Steam 라이브러리를 탐색하므로 Steam 설치를 찾을 수 있어야 합니다.

이 기능은 **로컬 워크샵 캐시 삭제**이며 구독 해제는 하지 않습니다. Steam이 구독 파일을 다시 내려받을 수 있고, 삭제한 캐시는 설치 실패 시 자동 복원되지 않습니다. 로컬 모드와 워크샵 모드의 중복을 정리해야 할 때 사용하세요.

## 서버 자동 접속

서버용 빌드는 메인 화면에서 **게임 계정명**과 **계정 비밀번호**만 입력합니다. Steam 로그인 정보가 아닙니다. **서버 입장 비밀번호는 제작자가 `launcher-build.json`의 `server_password`에 지정해 EXE에 포함**하며, 사용자에게 입력받거나 화면에 표시하지 않습니다. 계정 비밀번호는 설정 JSON에 저장하지 않고, 설정 창에서 저장하는 JSON에도 빌드에 포함된 서버 비밀번호를 복사하지 않습니다. 설정을 바꾸거나 런처를 다시 실행해도 EXE에 포함된 서버 비밀번호는 유지됩니다.

기본 빌드처럼 서버 주소가 비어 있으면 계정 입력 영역을 숨기고 일반 게임을 실행합니다. 서버 주소를 설정하거나 서버용으로 빌드하면 계정 입력 영역이 표시됩니다.

자동 접속을 위해 게임 폴더에 `media/lua/client/PZLauncherConnect.lua`, 사용자 Lua 폴더에 만료시간 10분의 `pz-launcher-request.txt`를 잠시 만듭니다. 요청에는 접속에 필요한 비밀번호가 임시로 들어가며, 게임이 소비할 때 비우고 실행 실패·게임 종료·런처 종료 시 정리합니다. 계정 비밀번호는 JVM 명령줄과 로그에 넣지 않습니다. 런처와 게임을 강제 종료하면 임시 파일이 남을 수 있지만 만료된 요청으로 자동 접속하지 않습니다. 다른 파일이 같은 Lua 경로에 있으면 덮어쓰지 않습니다.

## 모드팩 만들기

모드 원본 폴더에는 각 모드가 별도 폴더로 있어야 합니다. 루트 또는 Build 42의 버전 폴더에 `mod.info`를 포함해주세요.

```text
my-mods/
  ExampleMod/
    42/
      mod.info
      media/
```

```bat
python build_modpack.py --mods-dir "D:\my-mods" --out "D:\public-modpack" --version 1
```

생성한 배포 폴더를 HTTP(S) 서버에 올리고 해당 폴더의 URL을 `modpack_url`에 설정합니다. 운영 배포에는 HTTPS를 사용해주세요.

```text
public-modpack/
  manifest.json
  mods.zip
  mods/
    ExampleMod.zip
```

같은 출력 폴더에 버전을 올려 다시 빌드하면 변경·삭제 목록을 계산하고 이전 버전 기록을 이어갑니다.

```bat
python build_modpack.py --mods-dir "D:\my-mods" --out "D:\public-modpack" --version 2 --note "모드 갱신"
```

런처는 배포 도구가 생성한 SHA-256로 ZIP을 검증합니다. `archives` 해시가 없는 기존 manifest 형식도 지원하지만 그 배포에서는 ZIP 해시 검증을 생략합니다. ZIP의 경로와 압축파일 CRC는 확인하며, 설치를 별도 폴더에 준비한 뒤 교체합니다. 수동 설치는 네트워크 없이 가능한 모드 ZIP을 받아 설치하고 온라인 버전은 미확정으로 기록합니다. 개인 모드와 이름이 겹치면 자동으로 덮어쓰지 않습니다.

배포할 모드는 직접 관리하고 재배포 권한을 확인한 파일로 구성해주세요. 이 저장소에는 게임 파일·외부 모드·운영 서버 데이터가 포함되지 않습니다.

## 서버에서 자동 감지 및 서빙

Windows와 Linux에서 Python 3.11 이상만 있으면 실행합니다. 외부 라이브러리와 게임 서버 관리 API는 필요 없습니다.

```bash
python serve_modpack.py --mods-dir /home/user/Zomboid/mods --out /home/user/pz-modpack-public --host 0.0.0.0 --port 8080
```

Windows에서는 경로만 바꿔 실행하세요.

```bat
python serve_modpack.py --mods-dir "D:\Zomboid\mods" --out "D:\pz-modpack-public" --host 0.0.0.0 --port 8080
```

런처의 `modpack_url`은 `http://서버주소:8080/dist`로 지정합니다. 기본 호스트는 `127.0.0.1`이므로 다른 컴퓨터에서 접속하려면 위 예시처럼 `--host 0.0.0.0`과 해당 포트의 네트워크 접근을 준비하세요. HTTPS 프록시를 앞에 둘 때는 외부 HTTPS 주소의 `/dist`를 사용합니다. `--url-prefix`로 경로를 바꿀 수 있습니다.

시작할 때 최초 배포를 만들고, 기본 5초 간격으로 원본 파일의 이름·크기·수정시간을 확인합니다. 변경 후 두 번의 동일한 감지 결과를 확인한 뒤 내용을 해시하고 버전을 올려 자동 배포합니다. 감지 주기는 `--poll-interval 5`로 지정합니다. 재시작해도 내용이 같으면 기존 버전을 유지합니다. 실패하거나 복사 중 파일이 계속 바뀌면 기존 배포를 유지하고 다시 감지합니다.

`manifest.json`은 최신 버전을 가리키고, 각 버전의 ZIP은 `releases/v<번호>` 아래에 별도로 보관합니다. 런처는 manifest에 기록된 해당 버전의 URL로 다운로드하므로 배포 도중 새 버전이 나와도 파일이 섞이지 않습니다. 서버는 manifest와 모드 ZIP만 공개하며 원본 디렉터리·운영 설정·상태 파일은 서빙하지 않습니다. 변경되는 원본에는 실제 서버에서 사용하는 모드만 두세요. 버전별 전체 ZIP이 쌓이므로 디스크 사용량을 관리하고, 오래된 배포를 정리할 때는 그 버전을 다운로드 중인 사용자가 없는지 확인하세요.

스크립트는 실행 중일 때만 감지·서빙합니다. 장기 운영은 systemd 등 운영 환경의 프로세스 관리 도구에 등록해주세요. 종료는 Ctrl+C입니다.

## 개발 및 검증

런처 자체는 Python 표준 라이브러리와 Tkinter만 사용합니다. PyInstaller는 빌드할 때만 필요합니다.

```bat
python pz_mod_installer.py
python -m unittest discover -p "test_*.py" -v
```

Lua가 설치된 환경에서는 `lua tests/test_launcher_connect.lua`로 자동 접속의 일회성 소비·만료·즐겨찾기 중복 방지를 확인할 수 있습니다. Python 테스트는 임시 게임 폴더와 모의 프로세스를 사용하며 실제 게임 실행과 멀티플레이 접속을 대체하지 않습니다.

MIT License.
