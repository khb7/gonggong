# 배포 및 서버 확인 가이드

*마지막 실측: 2026-08-25*

오라클 클라우드 VM(Ubuntu 22.04) 한 대에서 FastAPI 백엔드가 systemd 서비스로 돌아간다.
`app/main.py` 가 `frontend/dist` 를 정적 서빙하므로 프로세스는 uvicorn 하나뿐이다.

공개 주소는 **https://bid.fp-desk.com** 이고, 경로는 이렇게 이어진다.

```
브라우저 → Cloudflare(프록시) → nginx(443) → 127.0.0.1:8000 uvicorn
```

uvicorn 은 `127.0.0.1:8000` 에만 바인딩되고 방화벽이 8000 을 막는다.
방화벽은 80/443 도 **Cloudflare 대역에서 오는 요청만** 허용하므로(`~/harden-origin.sh` 의 `CLOUDFLARE` 체인),
DNS 레코드의 프록시(주황 구름)를 끄면 사이트가 통째로 닫힌다.

서버 내부를 직접 볼 때는 여전히 SSH 터널을 쓴다(3절).

---

## 1. 접속 정보

| 항목 | 값 |
|------|-----|
| 공개 주소 | `https://bid.fp-desk.com` (Cloudflare 프록시 → nginx → uvicorn) |
| 서버 | `ubuntu@140.245.76.153` (Ubuntu 22.04, OpenSSH 8.9) |
| SSH 키 | `C:\Users\onebe\gonggong\ssh-key-2026-04-12.key` (실제 내용은 ed25519 `onebe-oci-20260722`, `~/.ssh/oci_key` 와 동일 파일) |
| 코드 경로 | `~/gonggong` |
| 서비스 | `gonggong.service` (systemd) |
| 바인딩 | `127.0.0.1:8000` — 외부 직접 접근 불가, nginx 프록시 경유 |
| nginx 설정 | `/etc/nginx/sites-available/gonggong` |
| 인증서 | `bid.fp-desk.com` (certbot webroot, 만료 2026-11-23) |
| DB | SQLite — `~/gonggong/data/gonggong.db` |
| git remote | `https://github.com/khb7/gonggong.git` |
| sudo | 비밀번호 없이 사용 가능 (`sudo -n` 통과) |

```bash
ssh -i "C:\Users\onebe\gonggong\ssh-key-2026-04-12.key" -o StrictHostKeyChecking=no ubuntu@140.245.76.153
```

> **파일명 주의**: `ssh-key-2026-04-12.key` 는 이름과 달리 2026-07-22 에 만든 ed25519 키다.
> 4월의 RSA 키는 서버에서 이미 폐기됐다(`authorized_keys` 에는 ed25519 한 개만 등록돼 있음).
> 짝이 안 맞던 옛 RSA 공개키는 `ssh-key-2026-04-12.key.pub.rsa-obsolete` 로 밀어 두고,
> `.pub` 은 실제 개인키에서 유도한 값으로 교체했다.
> **ssh 는 `-i` 로 준 개인키 옆의 `.pub` 을 먼저 읽어 서버에 제시**하므로,
> 이 둘이 어긋나면 개인키가 멀쩡해도 `Permission denied (publickey)` 가 난다.

---

## 2. 브라우저로 확인하기

공개 주소로 그냥 열면 된다 — https://bid.fp-desk.com

서버 내부를 직접 봐야 할 때(nginx 를 건너뛰고 오리진만 확인)는 SSH 터널을 쓴다.

```bash
# 로컬에서 터널 열기 (백그라운드)
ssh -f -N -i "C:\Users\onebe\gonggong\ssh-key-2026-04-12.key" \
    -o StrictHostKeyChecking=no -o ExitOnForwardFailure=yes \
    -L 8000:127.0.0.1:8000 ubuntu@140.245.76.153

# 확인
curl http://127.0.0.1:8000/health      # {"status":"ok"}
```

이후 브라우저에서:

- 프론트엔드 — `http://127.0.0.1:8000/`
- API 문서 — `http://127.0.0.1:8000/docs`

터널 종료: `ps aux | grep "ssh -f -N"` 로 PID 확인 후 `kill`.
로컬 8000 이 이미 개발 서버에 물려 있으면 `-L 8001:127.0.0.1:8000` 처럼 다른 포트를 쓴다.

---

## 3. 서버 상태 확인

```bash
sudo systemctl status gonggong          # 서비스 상태
sudo journalctl -u gonggong -n 50       # 최근 로그 (uvicorn.log 아님)
sudo journalctl -u gonggong -f          # 실시간 로그
cd ~/gonggong && git log --oneline -3   # 서버에 올라간 커밋
cd ~/gonggong && git status --short     # 서버 로컬 수정분
curl -s http://127.0.0.1:8000/health    # 서버 안에서 직접
```

---

## 4. 배포 절차

### 4-1. 코드 갱신

```bash
# 로컬
git push origin main
```

```bash
# 서버
cd ~/gonggong
git stash -- data/gonggong.db    # 서버 DB 가 운영 데이터 — pull 전 반드시 stash
git pull origin main
```

`git stash pop` 은 하지 않는다. 로컬 DB 변경분은 버려도 되는 값이다.
서버에 `app/main.py` 등 손으로 고친 파일이 남아 있을 수 있으니 pull 전 `git status` 로 확인할 것.

### 4-2. 프론트엔드

서버에 Node.js / npm 이 설치돼 있다(`/usr/bin/node`, `/usr/bin/npm`). 두 방법 다 가능하다.

```bash
# 방법 A — 서버에서 빌드
cd ~/gonggong/frontend && npm ci && npm run build
```

```bash
# 방법 B — 로컬 빌드 후 전송 (서버 자원 아낄 때)
cd frontend && npm run build
scp -i "C:\Users\onebe\gonggong\ssh-key-2026-04-12.key" -r dist/ \
    ubuntu@140.245.76.153:~/gonggong/frontend/
```

### 4-3. 재시작

```bash
sudo systemctl restart gonggong
sudo systemctl status gonggong
```

`kill` + `nohup` 방식은 쓰지 않는다. systemd 가 `Restart=on-failure` 로 관리한다.

---

## 5. 확인 시 함정

1. **브라우저 캐시** — `index.html` 이 강하게 캐시된다. 새 번들을 올려도 구 JS 가 실행돼 404 나 옛 UI 가 보인다.
   → `http://127.0.0.1:8000/?t=<timestamp>` 로 진입해 새 번들 로드를 확인한 뒤 SPA 내비게이션으로 이동한다. Playwright 도 동일.
2. **`http://140.245.76.153:8000` 은 열리지 않는다** — 방화벽 + 로컬 바인딩. 터널을 쓴다.
3. **`sudo` 섞인 명령을 `&&` 로 이어 붙이지 않는다** — 한 번에 하나씩 보낸다.
4. **삭제 대신 `mv`** — 서버 파일 교체는 `rm` 말고 `mv` 로 한다(롤백 용이).

---

## 6. systemd 유닛 (참고)

`/etc/systemd/system/gonggong.service`

```ini
[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/gonggong    # pydantic-settings 가 상대경로 .env 를 읽으므로 필수
ExecStart=/usr/bin/python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
ProtectSystem=full
ReadWritePaths=/home/ubuntu/gonggong
```

유닛을 고쳤다면 `sudo systemctl daemon-reload` 후 restart.

---

## 7. 로컬 실행 (참고)

```bash
uvicorn app.main:app --reload          # 백엔드 :8000
cd frontend && npm run dev             # 프론트 :5173 (CORS 허용됨)
```

---

## 8. 도메인 / HTTPS 구성 (2026-08-25 구축)

`bid.fp-desk.com` 은 fp-desk.com 존의 서브도메인이다. Cloudflare DNS 에 A 레코드
`bid → 140.245.76.153` 을 **Proxied(주황 구름)** 로 두었다. 회색 구름으로 바꾸면
방화벽이 Cloudflare 대역만 허용하므로 사이트가 닫힌다.

nginx 설정 사본: `deploy/nginx/bid.fp-desk.com.conf`
(서버 실제 경로는 `/etc/nginx/sites-available/gonggong`, `sites-enabled` 에 심볼릭 링크)

인증서는 fp-desk 와 같은 certbot webroot 방식으로 받았다.

```bash
sudo certbot certonly --webroot -w /var/www/certbot -d bid.fp-desk.com
sudo nginx -t
sudo systemctl reload nginx
```

클라이언트 실 IP 복원은 `/etc/nginx/conf.d/cloudflare-realip.conf` 가 전역 처리하므로
사이트 설정에 다시 적지 않는다.

### 새 서브도메인을 붙일 때 순서

인증서를 먼저 받으려 하면 실패한다. 80 블록 → certbot → 443 블록 순서를 지킨다.

1. Cloudflare DNS 에 A 레코드 추가 (Proxied)
2. nginx 에 80 블록만 올리고 reload — `/.well-known/acme-challenge/` → `/var/www/certbot`
3. certbot 발급
4. 443 블록 추가 후 `nginx -t` → reload

---

## 9. 일별 데이터 수집 (로컬 PC)

info21c 는 Playwright 로 브라우저를 띄워 로그인하고 Excel 을 받는다. 서버는
RAM 이 부족하고(956MB 중 여유 472MB) info21c 가 동시 접속을 막으므로,
**수집은 로컬 PC 에서 돌리고 결과 DB 만 서버로 올린다.**

### 수동 실행

```bash
python scripts/daily_collect.py                     # 최근 30일 중 빈 날짜
python scripts/daily_collect.py --days 90           # 최근 90일
python scripts/daily_collect.py --start 20251224 --end 20260131
```

아직 참여자 데이터가 없는 날짜만 골라 받으므로, 여러 번 돌려도 중복 수집되지 않는다.

### 작업 스케줄러 등록

PC 를 매일 켜지 않아도 되도록 "놓친 작업 따라잡기"를 쓴다.

1. `작업 스케줄러` 실행 → **작업 만들기** (기본 작업 아님)
2. **일반** 탭 — 이름 `gonggong 일별 수집`, "사용자가 로그온할 때만 실행" 유지
3. **트리거** 탭 — 새로 만들기 → 매일 03:00
4. **동작** 탭 — 새로 만들기
   - 프로그램: `python`
   - 인수: `scripts/daily_collect.py --headless`
   - 시작 위치: `C:\Users\onebe\gonggong`
5. **설정** 탭 — **"예약된 시작을 놓친 경우 가능한 한 빨리 작업 시작"** 체크 ← 핵심
6. 확인

이 옵션 덕분에 PC 가 꺼져 있던 날의 작업은 다음에 켤 때 실행되고,
그때 빈 날짜를 한꺼번에 메운다.

### 첫 실행 주의

마지막 수집이 **2025-12-24** 라 공백이 길다. 한 번에 돌리면 오래 걸리므로
첫 회는 기간을 나눠 수동으로 돌린 뒤 스케줄러에 맡긴다.

```bash
python scripts/daily_collect.py --start 20251224 --end 20260131
python scripts/daily_collect.py --start 20260201 --end 20260331
# ... 이어서
```
