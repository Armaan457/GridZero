# Docker guide - P2P Energy Engine (for the teammate who hosts it)

The image contains the whole engine: API, simulation, dashboard (`/`), API docs (`/docs`). Nothing else is needed to run it.
It starts on **SQLite** by default (works with zero setup) and switches to **DynamoDB** with environment variables.

> Not built in the author's environment (no Docker there). The same install + start steps were run in a clean Python
> environment and all endpoints worked, but do the build once and check `docker logs` before relying on it.

## 1. Quick start (2 minutes)
```bash
cd p2p_engine            # the folder with Dockerfile + server.py
docker build -t p2p-engine .
docker run -d --name p2p-engine -p 8000:8000 -v p2p-data:/data p2p-engine
```
Open http://localhost:8000 (dashboard), http://localhost:8000/docs (API), http://localhost:8000/health.
Or with compose: `cp .env.example .env` then `docker compose up --build -d`.

## 2. Settings (environment variables)
| Variable | Default | Meaning |
|---|---|---|
| `DB_BACKEND` | `sqlite` | `sqlite` (file in `/data`) or `dynamodb` |
| `SQLITE_PATH` | `/data/p2p.db` | SQLite file location (keep the `/data` volume to survive container restarts) |
| `AWS_REGION` | `ap-southeast-2` | DynamoDB region. **This account only allows ap-southeast-2 (Sydney)** |
| `DDB_TABLE_PREFIX` | `p2p_` | DynamoDB table prefix (change if several people share one AWS account) |
| `DDB_ENDPOINT` | empty | Only for DynamoDB Local (`http://dynamodb-local:8000`) |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | empty | Needed only when NOT running on AWS with an IAM role |
| `FORECAST_URL` | empty | URL of the ML agent (`POST`, returns `{"pred_load","pred_solar"}`). Empty/down -> built-in baseline forecaster |
| `ADMIN_TOKEN` | empty | If set, all POST/PATCH/DELETE calls need header `X-Admin-Token: <token>` (GETs stay open). **Set this on a public server.** |
| `READINGS_CSV` | empty | Optional dataset (`node_id,hour,load_kwh[,solar_kwh]`) mounted into the container |

Pass them with `-e NAME=value`, `--env-file .env`, or the compose `.env` file. **Never put keys in the Dockerfile or commit `.env`.**

## 3. Run on DynamoDB
**On your laptop (access keys):**
```bash
docker run -d --name p2p-engine -p 8000:8000 \
  -e DB_BACKEND=dynamodb -e AWS_REGION=ap-southeast-2 \
  -e AWS_ACCESS_KEY_ID=... -e AWS_SECRET_ACCESS_KEY=... \
  -e ADMIN_TOKEN=choose-a-secret p2p-engine
```
**On EC2 / ECS (recommended): attach an IAM role with DynamoDB permission and pass no keys:**
```bash
docker run -d --name p2p-engine --restart unless-stopped -p 8000:8000 \
  -e DB_BACKEND=dynamodb -e AWS_REGION=ap-southeast-2 -e ADMIN_TOKEN=choose-a-secret p2p-engine
```
EC2 gotcha: if the log shows `NoCredentialsError`, the container cannot reach the instance role. In the EC2 console:
Instance -> Actions -> Instance settings -> **Modify instance metadata options** -> set **Metadata response hop limit = 2**
(or start the container with `--network host`).

The engine creates its four tables on first start: `p2p_meter`, `p2p_ledger`, `p2p_events`, `p2p_config`.
The IAM policy needs `CreateTable, DescribeTable, ListTables, PutItem, GetItem, BatchWriteItem, DeleteItem, Query, Scan`
(see `AWS_DYNAMODB_SETUP.md`; for a `p2p_*` table-restricted policy add `dynamodb:GetItem`).

## 4. Where the data lives (important)
- **Houses, appliances, weather, settings and the simulation clock are saved after every simulated hour** (SQLite file or the `p2p_config` table). Restart the container and it continues where it stopped.
- Ledger/meter history is in the database too. With SQLite keep `-v p2p-data:/data`, otherwise a re-created container starts empty.
- To start fresh: press **Reset** on the dashboard (keeps houses) or call `POST /reset?defaults=true` (original 10 homes).

## 5. Run exactly ONE container
The simulation clock lives in the process. Two containers (or `--workers 2`) would simulate two different worlds
and write over each other's rows. For availability use `--restart unless-stopped`, not more copies.

## 6. Share / publish the image
**As a file (no registry needed):**
```bash
docker save p2p-engine | gzip > p2p-engine.tar.gz         # send this file
gunzip -c p2p-engine.tar.gz | docker load                  # teammate loads it
```
**Amazon ECR (Sydney).** First check ECR is allowed on the account: `aws ecr describe-repositories --region ap-southeast-2`.
```bash
aws ecr create-repository --repository-name p2p-engine --region ap-southeast-2
aws ecr get-login-password --region ap-southeast-2 | docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.ap-southeast-2.amazonaws.com
docker tag p2p-engine:latest <ACCOUNT_ID>.dkr.ecr.ap-southeast-2.amazonaws.com/p2p-engine:latest
docker push <ACCOUNT_ID>.dkr.ecr.ap-southeast-2.amazonaws.com/p2p-engine:latest
```
Pull on the server with the same login command, then `docker run ... <ACCOUNT_ID>.dkr.ecr...../p2p-engine:latest`.
**Docker Hub:** `docker tag p2p-engine <user>/p2p-engine:latest && docker push <user>/p2p-engine:latest` (use a private repo).

## 7. Host it (EC2 is the simplest)
1. Launch Ubuntu 24.04 EC2 in **ap-southeast-2** with an IAM role (DynamoDB) and a security group opening 22 (your IP) and 8000.
2. `sudo apt-get update && sudo apt-get install -y docker.io && sudo usermod -aG docker $USER` (log out/in).
3. Load or pull the image (section 6) and run the DynamoDB command from section 3.
4. Test `curl localhost:8000/health`, then open `http://<public-ip>:8000`.
5. HTTPS: a website served over https cannot call an http API from the browser. Use the Next.js rewrite proxy, or put CloudFront / a domain with Caddy in front (see `DEPLOY_AWS.md`).
ECS Fargate also works: use the same image, port 8000, one task, the same environment variables, a task role with DynamoDB permission, and an ALB health check on `/health`.

## 8. Update to a new version
```bash
docker build -t p2p-engine .
docker rm -f p2p-engine
docker run -d --name p2p-engine ...same flags...
```
State survives (SQLite volume or DynamoDB).

## 9. Handy commands
```bash
docker logs -f p2p-engine          # live logs (look for "[db] DynamoDB region: ap-southeast-2")
docker ps                          # STATUS shows (healthy) after ~30 s
docker exec -it p2p-engine sh      # shell inside
curl localhost:8000/health         # {"ok":true,"db_backend":"dynamodb",...}
```

## 10. Troubleshooting
| Symptom | Fix |
|---|---|
| `port is already allocated` | Another process uses 8000. Stop it, or use `-p 8001:8000` |
| Container exits at once | `docker logs p2p-engine`. Usually a bad env value or missing AWS permission |
| `AccessDeniedException ... service control policy` | Region is not ap-southeast-2 (the account's organization blocks other regions) |
| `NoCredentialsError` | Pass keys, or on EC2 attach the IAM role and set metadata hop limit 2 |
| Dashboard shows a red "Engine error" bar | `docker logs` has the traceback; the engine paused itself instead of failing silently |
| 401 on POST calls | `ADMIN_TOKEN` is set: send `X-Admin-Token`; the dashboard asks for it once per browser session |
| Data gone after re-creating the container | You ran SQLite without `-v p2p-data:/data` |
| `(unhealthy)` in `docker ps` | The server is not answering on 8000 inside the container; read the logs |
