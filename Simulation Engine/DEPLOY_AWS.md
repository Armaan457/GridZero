# Hosting the engine on AWS (EC2 + DynamoDB, region ap-southeast-2)

> Prefer containers? `DOCKER.md` has the image, the run commands and the ECR steps. This file is the no-Docker route (systemd on EC2).
> Set a secret before exposing the server: add `Environment=ADMIN_TOKEN=<secret>` to the service file; all POST/PATCH/DELETE calls then need the `X-Admin-Token` header.
> The engine now creates a 4th table, `p2p_config` (needs `dynamodb:GetItem` too).

Why EC2: it is the simplest service that keeps ONE long-running Python process (the simulation clock lives in memory).
AWS App Runner is not an option: AWS says it is no longer open to new customers.
Everything must stay in **ap-southeast-2 (Sydney)** because your account's organization policy blocks other regions.

```
Next.js website  ->  EC2 (uvicorn :8000)  ->  DynamoDB (ap-southeast-2)
                         ^
                    IAM role (no keys stored on the server)
```

## 0. Check that EC2 and IAM roles are allowed (PowerShell, any folder)
```
aws ec2 describe-instances --region ap-southeast-2
aws iam list-roles --max-items 1
```
A normal result (even empty) = allowed. An "explicit deny in a service control policy" = blocked; see "If a step is blocked" at the end.

## 1. Prepare and push the code (project folder)
1. Make sure the folder with `server.py` is in your GitHub repo (yours is `Simulation Engine`). `.gitignore` in this folder keeps `p2p.db`, `.env`, `*.pem` and `__pycache__` out of Git. **Never commit access keys or .pem files.**
2. Push: `git add . ; git commit -m "engine with DynamoDB + deploy files" ; git push`.
3. If the repo is private, use the zip/scp method in step 5B.

## 2. Create an IAM role for the server (so no keys are needed on it)
Console -> IAM -> Roles -> Create role -> Trusted entity: **AWS service** -> Use case **EC2** -> Next ->
attach **AmazonDynamoDBFullAccess** (or your custom `p2p_*` policy) -> name it `p2p-engine-role` -> Create role.

## 3. Launch the EC2 instance
Console -> top right region **Asia Pacific (Sydney) ap-southeast-2** -> EC2 -> **Launch instance**:
- Name: `p2p-engine`
- AMI: **Ubuntu Server 24.04 LTS**
- Instance type: **t3.micro** (or the type marked "Free tier eligible" if your account has it)
- Key pair: **Create new key pair** (RSA, `.pem`), download and keep it safe
- Network settings -> Edit: auto-assign public IP **Enable**; create a security group with
  - SSH, port 22, source **My IP**
  - Custom TCP, port **8000**, source **Anywhere (0.0.0.0/0)** (temporary, for the demo)
- Advanced details -> **IAM instance profile**: `p2p-engine-role`
- Launch. When "Running", copy the **Public IPv4 address**.

## 4. Connect from Windows PowerShell
```
cd C:\path\where\the\pem\is
ssh -i p2p-key.pem ubuntu@<PUBLIC_IP>
```
If it says the key is "too open": right-click the .pem -> Properties -> Security -> Advanced, disable inheritance and keep only your user with read access, then retry. Type `yes` at the first prompt.

## 5. Install and start the engine (inside the SSH session)
**A. From GitHub (public repo):**
```
curl -O https://raw.githubusercontent.com/<you>/<repo>/<branch>/Simulation%20Engine/deploy/setup.sh
bash setup.sh https://github.com/<you>/<repo>.git "Simulation Engine"
```
(Or just paste the contents of `deploy/setup.sh` into `nano setup.sh`, save, and run `bash setup.sh <repo-url> "Simulation Engine"`.)

**B. Without Git (private repo):** zip the contents of the `Simulation Engine` folder on your PC, then from PowerShell:
```
scp -i p2p-key.pem engine.zip ubuntu@<PUBLIC_IP>:~/
```
and on the server:
```
sudo apt-get update -y && sudo apt-get install -y unzip python3-venv python3-pip
sudo mkdir -p /opt/p2p_engine && sudo chown $USER: /opt/p2p_engine
unzip ~/engine.zip -d /opt/p2p_engine && cd /opt/p2p_engine
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
sudo cp deploy/p2p-engine.service /etc/systemd/system/ && sudo sed -i "s/__USER__/$USER/" /etc/systemd/system/p2p-engine.service
sudo systemctl daemon-reload && sudo systemctl enable --now p2p-engine
```
The service (`deploy/p2p-engine.service`) sets `DB_BACKEND=dynamodb` and `AWS_REGION=ap-southeast-2`, runs ONE uvicorn process, and restarts it if it crashes or the server reboots.

## 6. Test
- On the server: `curl localhost:8000/health` -> `{"ok":true,"db_backend":"dynamodb",...}`
- In your browser: `http://<PUBLIC_IP>:8000` (dashboard), `/docs`, `/health`. Press Reset then Start and check rows appear in DynamoDB (Sydney).
- Logs if something is wrong: `sudo journalctl -u p2p-engine -n 50 --no-pager`

## 7. Connect the website and the agent
- Set the frontend variable: `NEXT_PUBLIC_ENGINE_URL=http://<PUBLIC_IP>:8000`.
- **HTTPS problem:** a website served over `https://` (e.g. Vercel) cannot call an `http://` API from the browser (mixed content). Pick one:
  1. **Next.js proxy (easiest):** in `next.config.js` add `async rewrites() { return [{ source: "/engine/:path*", destination: "http://<PUBLIC_IP>:8000/:path*" }]; }` and call `/engine/state` from the browser. The request then goes server-to-server.
  2. **CloudFront in front of EC2** (gives a free `https://xxxx.cloudfront.net` URL) if CloudFront is allowed in your account.
  3. A domain + Caddy/nginx on the server with a free certificate.
- **Agent:** it must be reachable from the server by URL. Uncomment `Environment=FORECAST_URL=...` in `/etc/systemd/system/p2p-engine.service`, then `sudo systemctl daemon-reload && sudo systemctl restart p2p-engine`. `/state` then shows `forecast_source: "agent"`.

## 8. Keep the address stable
The public IP changes when the instance is stopped and started. Console -> EC2 -> Elastic IPs -> Allocate -> Associate to the instance. (AWS charges a small hourly fee for public IPv4 addresses.)

## 9. Updating the code later
`ssh` in, then `bash setup.sh <repo-url> "Simulation Engine"` again (it re-clones and restarts). Press Reset on the dashboard afterwards.

## 10. Security and cost (be honest in the submission)
- Port 8000 is open to everyone. Set `ADMIN_TOKEN` so the control/editing endpoints need a secret header; reads stay public.
- The IAM role means no AWS keys live on the server. Do not put keys in the service file.
- A t3.micro plus public IP costs a few dollars a month. Check with the account owner who pays. Stop the instance when not demoing, and terminate it (plus delete the DynamoDB tables) when finished.
- Run exactly one engine instance (one process, one server): the simulation clock is in memory, so two copies would show two different worlds.

## If a step is blocked
| Blocked | Fallback |
|---|---|
| EC2 | Lightsail (`aws lightsail get-instances --region ap-southeast-2`) with the same steps, or ECS Fargate |
| IAM role creation | Put an access key in the service file (`Environment=AWS_ACCESS_KEY_ID=...`), restrict the key to DynamoDB, and rotate it afterwards |
| All AWS compute | Host the engine on Render/Railway/Fly.io with `DB_BACKEND=dynamodb`, `AWS_REGION=ap-southeast-2` and a key limited to DynamoDB, or keep SQLite on the host's disk |
