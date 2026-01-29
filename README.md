# 🌌 ORION_AI Project

ORION_AI는 Python 기반의 인공지능 프로젝트로, 버전별(V1~V4) 점진적인 기능 개선을 포함하고 있습니다.

## 📂 프로젝트 구조

```text
ORION_AI/
├── V1.py             # 초기 버전 (기본 기능)
├── V2.py             # 기능 개선 버전
├── V3.py             # 안정화 버전
├── V4.py             # 최신 업데이트 버전
├── UpdateLog.txt     # 업데이트 변경 사항 기록
├── user_profile.txt  # 사용자 설정 프로필
└── .env              # 환경 변수 설정 (보안상 업로드 제외)
🚀 시작하기
1. 환경 설정
이 프로젝트는 Python 3.12 환경에서 테스트되었습니다. 가상환경을 생성하고 필요한 패키지를 설치하세요.

Bash
# 가상환경 생성
python -m venv venv

# 가상환경 활성화 (Windows)
.\venv\Scripts\activate

# 가상환경 활성화 (Mac/Linux)
source venv/bin/activate
2. API 설정
Google 서비스 연결을 위해 credentials.json과 token.json 파일이 필요할 수 있습니다. (설정에 따라 .env 파일에 필요한 API Key를 입력하세요.)

3. 실행 방법
가장 최신 버전인 V4.py를 실행하려면 아래 명령어를 입력하세요.

Bash
python V4.py
📝 업데이트 기록
상세한 변경 사항은 UpdateLog.txt 파일에서 확인할 수 있습니다.

© 2026 ORION_AI Project. All rights reserved.


---

### 💡 팁
* **V1~V4의 차이점**: 만약 각 버전별로 구체적인 차이(예: V3는 브레인 모듈 추가, V4는 UI 개선 등)가 있다면 `프로젝트 구조` 섹션 옆에 짧게 메모를 남겨주면 더 좋습니다.
* **파일 업로드**: `README.md`를 저장한 후 다시 터미널에서 아래 명령어를 입력해야 깃허브에 반영됩니다.

```bash
git add README.md
git commit -m "Add README.md"
git push
