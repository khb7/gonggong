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
| **사양** | **OCI `VM.Standard.E2.1.Micro` — 1 OCPU / RAM 1GB.** 이 사양이 설계 제약이다. 10절 참고 |
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

#### `git pull` 이 인증에 막힐 때 (2026-08-28 실제로 막혔다)

서버에 GitHub 자격증명이 없다 — `could not read Username for 'https://github.com'`.
계정 설정(배포 키 발급)을 건드리지 않고 **git bundle** 로 넘기면 히스토리가 온전히 유지된다.

```bash
# 로컬 — 15MB 정도다
git bundle create /tmp/gg.bundle main
scp -i "C:\Users\onebe\gonggong\ssh-key-2026-04-12.key" /tmp/gg.bundle \
    ubuntu@140.245.76.153:/tmp/gg.bundle
```

```bash
# 서버
cd ~/gonggong && git pull --ff-only /tmp/gg.bundle main
```

`data/gonggong.db` 가 옛 커밋에 추적돼 있어 충돌하면, DB 를 잠시 밀어두고 pull 한 뒤
되돌린다. **`git stash` 를 쓰면 안 된다** — 새 DB 가 스태시로 들어가고 옛 버전이 복원된다.

```bash
mv ~/gonggong/data/gonggong.db /tmp/keep.db
cd ~/gonggong && git checkout -- data/gonggong.db && git pull --ff-only /tmp/gg.bundle main
mv /tmp/keep.db ~/gonggong/data/gonggong.db && chmod 664 ~/gonggong/data/gonggong.db
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

### 4-3. 데이터(DB) 배포 — **사전계산을 먼저 돌린다**

DB 는 git 으로 가지 않는다. 로컬에서 만들어 파일째 보낸다.

> ⚠ **`scripts/build_offset_histogram.py` 를 로컬에서 먼저 돌려야 한다.**
> ETL 로 데이터를 갱신했으면 사전계산도 다시 만들어야 하고, 그걸 빼먹으면
> 서버가 참여자 4.6M 행을 실시간 스캔한다. 2026-08-28 에 그렇게 서버가 멈췄다(10절).
> **서버에서 돌리면 안 된다** — 애초에 피하려던 그 스캔을 그대로 하게 된다.

```bash
# 1. 로컬 — 적재 후 반드시 이 순서
python scripts/etl_csv.py --file <각 파일> --upsert
python scripts/build_offset_histogram.py          # 19 스코프 / 9,297 bin / 35초 (2026-09-10 실측)
python scripts/validate_data.py                   # FAIL 0 확인
```

```bash
# 2. 압축해서 전송 (703MB → 205MB)
gzip -c data/gonggong.db > /tmp/gg.db.gz
scp -i "C:\Users\onebe\gonggong\ssh-key-2026-04-12.key" /tmp/gg.db.gz \
    ubuntu@140.245.76.153:/tmp/gg.db.gz
```

```bash
# 3. 서버 — 교체 **전에** 무결성과 내용을 확인한다
gunzip -f /tmp/gg.db.gz
python3 -c "
import sqlite3; c=sqlite3.connect('/tmp/gg.db')
print(c.execute('PRAGMA quick_check').fetchone()[0])
for t in ('bids_history','bid_participants','offset_histogram','offset_scope_stat'):
    print(t, c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0])
"
```

```bash
# 4. 교체 — rm 쓰지 말고 mv 로. 롤백이 mv 한 번이 된다
sudo systemctl stop gonggong
mv ~/gonggong/data/gonggong.db ~/gonggong/data/gonggong.db.$(date +%Y%m%d)
mv /tmp/gg.db ~/gonggong/data/gonggong.db
chmod 664 ~/gonggong/data/gonggong.db
sudo systemctl start gonggong
```

마이그레이션은 보통 필요 없다 — 로컬에서 이미 적용된 DB 를 통째로 보내기 때문이다.
`python3 -m alembic current` 가 head 인지만 확인한다.

### 4-4. 재시작

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

## 9. 데이터 수집 (로컬 PC, 주 1회 수동)

info21c 는 Playwright 로 브라우저를 띄워 로그인하고 Excel 을 받는다. 서버는
RAM 이 부족하고(956MB) info21c 가 동시 접속을 막으므로,
**수집은 로컬 PC 에서 돌리고 결과 DB 만 서버로 올린다.**

### 주 1회 루틴

```bash
python scripts/daily_collect.py --days 14        # 1) 수집 (두 leg + 고아 검사)
python scripts/build_offset_histogram.py         # 2) 사전계산 (35초)
python scripts/validate_data.py                  # 3) 품질 확인 (WARN 눈으로 볼 것)
                                                 # 4) DB 전송·교체 → 4-3절
```

아직 참여자 데이터가 없는 날짜만 골라 받으므로, 여러 번 돌려도 중복 수집되지 않는다.

**2~4 는 빼먹으면 안 된다.** 사전계산을 안 만들면 서버가 참여자 590만 행을
실시간 스캔하고, 그러다 2026-08-28 에 VM 이 스래싱으로 멈췄다 (10절).

### 작업 스케줄러를 쓰지 않는 이유 (2026-09-10 결정)

자동화할 수 있는 건 1번뿐이고, 2~4 는 사람이 봐야 의미가 있다 —
`validate_data.py` 의 WARN, 고아 증가, 253MB 업로드 타이밍은
자동으로 돌려봐야 아무도 안 읽는다. 주 1회 수동이 실제로 더 안전하다.

옛 절차(매일 03:00 + "놓친 작업 따라잡기")는 git 이력에 있다.

### `daily_collect.py` 는 두 leg 를 모두 돈다

```
1. 목록 leg   공고 Excel   → bids_history       (collect_notices)
2. 참여자 leg 참여자 Excel → bid_participants   (info21c_participants.run)
```

**순서가 중요하다.** `update_bid_type_and_method()` 가 공고 행을 UPDATE 만 하고
`if row:` 가드로 감싸여 있어서, 참여자를 먼저 넣으면 `bid_type` / `price_method`
가 영영 빈 채로 남는다.

> ⚠ **2026-05-31 ~ 09-10: 목록 leg 가 배선돼 있지 않았다.**
> 참여자만 들어오고 공고가 안 들어와 조인에서 떨어지는 "고아 공고"가 누적됐다
> (최대 401건). 에러가 0건이라 넉 달간 드러나지 않았다.
> 지금은 실행 끝에 고아 수를 세고 **늘었으면 종료 코드 1** 로 죽는다.
> 남은 고아 235건은 시기 특정이 안 돼(옛 로그 포맷) 미해결로 남아 있다.

### 목록 Excel 은 현재 페이지만 내보낸다

`pageSize=100` 으로 키워도 결과가 100건을 넘으면 나머지가 조용히 잘린다.
`info21c_downloader.goto_next_page()` 가 페이지를 순회하며 페이지마다 파일을
하나씩 만든다 (`_p2`, `_p3`, ...). **받은 파일을 전부 적재해야 한다.**

실측 (실내건축 2026-08-29~09-09): 1페이지 100건 + 2페이지 23건 = 123건.
페이지네이션 없이는 100건에서 끊겨 23건이 사라졌다.

## 10. 서버 사양 제약 — RAM 1GB

`VM.Standard.E2.1.Micro` 는 **1 OCPU / RAM 1GB** 다. DB 는 703MB 라 페이지 캐시에
다 못 올라간다. 로컬 성능은 이 서버의 근거가 되지 못한다.

### 2026-08-28 사고

703MB DB 를 올린 뒤 분포 요청이 참여자 **4,490,350 행을 파이썬 리스트로** 끌어오면서
스래싱 → SSH·HTTP 모두 응답 불가 → VM 강제 재부팅.

로컬은 RAM 이 넉넉해 문제가 안 보였고, 그전 서버 DB 는 참여자가 52 행뿐이라
한 번도 드러난 적이 없었다.

원인은 두 겹이었고 서버에서 재서 갈랐다.

| | 문제 | 확인 |
|---|---|---|
| 메모리 | 4.5M 행을 파이썬으로 집계 | SQL 집계는 RSS **14.6MB** |
| 속도 | 4.5M 행 스캔 자체 | 필터 없이도 68.8s — 특정 필터 탓이 아니었다 |

수정 후 (같은 서버에서 실측):

```
global               0.001s   ← 69.1s 였다
region(경기)          0.001s   ← 22.3s 였다
client(화성시+조경)     0.347s   (사전계산 없음 — 실시간)
최대 RSS 13.1 MB     서비스 메모리 157MB
```

### 지켜야 할 것

1. **행을 파이썬으로 끌어오지 말 것.** 집계는 SQL 에서 한다.
   `bid_participants` 는 4,656,914 행이다.
2. **넓은 스코프는 사전계산.** `scripts/build_offset_histogram.py` 를 **로컬에서** 돌린다.
3. **SQLite `alter_column` 금지.** 테이블 재작성(복사)을 유발한다.
   `bid_participants` 에 걸면 이 사양에서 위험하다. alembic autogenerate 가
   무관한 `NOT NULL` 변경을 끼워 넣는 일이 있으니 마이그레이션을 눈으로 확인할 것.
4. **배포 전 서버에서 재라.** DB 파일만 `/tmp` 에 놓고 쿼리 시간과 RSS 를 측정한 뒤
   교체한다. 이 한 단계가 사고를 막는다.

### 서버가 스래싱으로 굳었을 때

SSH 가 `Connection timed out during banner exchange` 로 막힌다 — sshd 를 fork 할
여유조차 없다는 뜻이다. 콘솔의 **Running** 은 전원 상태일 뿐 OS 건강이 아니다.

OCI 콘솔 → Compute → Instances → 인스턴스 → **Reboot** 시 반드시
**Force reboot**(또는 More actions → Reset)를 쓴다. 일반 Reboot 은 OS 의 정상 종료를
기다리다 실패한다.
