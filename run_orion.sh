#!/bin/bash

# ==========================================
#  Orion C2 Portable - 휴대용 실행 스크립트
# ==========================================
#
#  맥북 덮개 닫아도 계속 실행됨!
#  블루투스 이어폰으로 Hey Orion 하세요
#
# ==========================================

echo "🚀 Orion C2 Portable 시작..."
echo ""
echo "📌 사용법:"
echo "   - 블루투스 이어폰 연결하고 맥북 덮개 닫기"
echo "   - 'Hey Orion, [명령]' 으로 호출"
echo "   - 종료: 'Hey Orion, goodbye' 또는 Ctrl+C"
echo ""

# 맥북 잠자기 방지 + 파이썬 실행
# -s: 전원 연결 시 잠자기 방지
# -i: 프로세스가 실행 중이면 잠자기 방지
caffeinate -si python3 C2_Portable.py

echo ""
echo "👋 Orion C2 종료됨"