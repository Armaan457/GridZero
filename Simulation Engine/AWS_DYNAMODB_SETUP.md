# Switching the engine from SQLite to Amazon DynamoDB

The code now supports **both** databases. You choose with one environment variable, so you can always fall back to SQLite if AWS misbehaves.

| `DB_BACKEND` | Database | Setup |
|---|---|---|
| `sqlite` (default) | local file `p2p.db` | none |
| `dynamodb` | Amazon DynamoDB | this guide |

## Why a database at all?
The simulation itself does not need one: the engine keeps everything in Python lists while it runs. The database exists for four reasons:
1. **Persistence.** Restarting the server (or a crash) would otherwise erase every ledger entry.
2. **Querying for the website.** `/ledger/B` and `/statement/B` read stored history instead of recomputing.
3. **Audit trail.** A ledger of who sold to whom is the core of a P2P trading product; it must be stored.
4. **AWS/Lambda.** Lambda functions forget everything between calls, so state has to live in a database (DynamoDB is the natural AWS choice).
SQLite was just the zero-setup option. DynamoDB does the same job and fits the AWS story.

## Tables created (automatically on first run; this account only allows region ap-southeast-2)
| Table | Key | What one item is |
|---|---|---|
| `p2p_meter` | `node` (partition) + `slot` (sort, = day*24+hour) | one home in one hour: readings, forecast, P2P units, grid units, money |
| `p2p_ledger` | `pk`="TX" + `sk`="000012#A#B" | one seller->buyer transaction |
| `p2p_events` | `pk`="EVT" + `sk`="000012#<timestamp>" | one live event line |
| `p2p_config` | `k`="state" | the whole engine state as JSON (houses, appliances, weather, settings, clock) so a restart continues |
All on-demand billing (no capacity planning). Writes are idempotent (same key overwrites), so replays never double count.
Why it fits: the website's questions are "latest N rows of one home" (partition + sorted key = one cheap Query) and "latest N transactions" (one Query on the ledger partition).

## Steps

### 1. AWS account and region
Sign in to the AWS Console and choose a region in the top right (the code defaults to **ap-south-1 Mumbai**; any region works, just keep it consistent).

### 2. Create an IAM user for the engine (do not use the root account)
Console -> IAM -> Users -> Create user (e.g. `p2p-engine`) -> attach a policy.
- Fastest for a hackathon: attach **AmazonDynamoDBFullAccess**.
- Tighter (recommended if you have 5 minutes): create this inline policy (replace `ACCOUNT_ID` with your 12-digit account number, shown top right in the console):
```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": ["dynamodb:ListTables"], "Resource": "*" },
    { "Effect": "Allow",
      "Action": ["dynamodb:CreateTable","dynamodb:DescribeTable","dynamodb:GetItem","dynamodb:PutItem","dynamodb:BatchWriteItem",
                 "dynamodb:DeleteItem","dynamodb:Query","dynamodb:Scan"],
      "Resource": "arn:aws:dynamodb:ap-south-1:ACCOUNT_ID:table/p2p_*" }
  ]
}
```
Then: user -> Security credentials -> **Create access key** -> "Command Line Interface" -> copy the Access key ID and Secret. **Never commit these to GitHub or paste them in chat.**

### 3. Install the AWS CLI and log in with those keys
Install from https://aws.amazon.com/cli/ then:
```bash
aws configure
# AWS Access Key ID:     <paste>
# AWS Secret Access Key: <paste>
# Default region name:   ap-south-1
# Default output format: json
aws sts get-caller-identity      # should print your account and user
```
(boto3, which the engine uses, reads the same credentials automatically.)

### 4. Install the new dependency
```bash
pip install -r requirements.txt      # now includes boto3
```

### 5. Run the engine with DynamoDB
Mac/Linux:
```bash
DB_BACKEND=dynamodb AWS_REGION=ap-south-1 uvicorn server:app --port 8000
```
Windows PowerShell:
```powershell
$env:DB_BACKEND="dynamodb"; $env:AWS_REGION="ap-south-1"; uvicorn server:app --port 8000
```
On first start the engine creates the three tables (takes a few seconds). Optional: `DDB_TABLE_PREFIX=mytest_` to use different table names.

### 6. Verify it really writes to DynamoDB
1. Open the dashboard (`http://localhost:8000`), press **Start**, let a few hours run.
2. AWS Console -> DynamoDB -> **Tables** -> `p2p_meter` -> **Explore table items**. You should see rows (`node`, `slot`, `load`, ...).
3. Stop the server, start it again: `GET /ledger/B` still returns the old rows only if you do not press Reset (persistence works). Note the simulation clock restarts at day 0 on every server start, so press **Reset** after a restart to avoid mixing old and new runs.

### 7. (Optional) Offline development with DynamoDB Local
```bash
docker run -p 8001:8000 amazon/dynamodb-local
DB_BACKEND=dynamodb DDB_ENDPOINT=http://localhost:8001 AWS_ACCESS_KEY_ID=x AWS_SECRET_ACCESS_KEY=x AWS_REGION=ap-south-1 uvicorn server:app --port 8000
```

### 8. Run the equivalence test (needs no AWS account)
```bash
pip install moto httpx
python test_db_backends.py
```
It runs the same simulation on SQLite and on a mocked DynamoDB and checks `/ledger`, `/statement`, `/ledger_all`, `/events` and reset return **identical** results. I ran it: all identical.

## What changed in the code
- `db.py` now only selects the backend and has `statement_totals()`; `db_sqlite.py` is the old SQLite code; `db_dynamo.py` is new.
- `server.py` no longer contains SQL; it calls `db.insert_*`, `db.meter_rows`, `db.ledger_all`, `db.events`.
- `engine.py` meter rows now carry `p2p_earned_rs`, `p2p_owed_rs`, `grid_fee_rs`, so a statement is just sums over one home's rows.
- API responses are unchanged, so the frontend needs no changes.

## Cost
On-demand DynamoDB charges per request. A demo writes a few dozen items per simulated hour, which is far inside the free tier. Delete the tables after the hackathon (Console -> Tables -> Delete) if you want zero cost.

## Troubleshooting
| Error | Fix |
|---|---|
| `NoCredentialsError` | Run `aws configure`, or set `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` |
| `AccessDeniedException ... CreateTable/ListTables` | Policy missing actions or wrong `ACCOUNT_ID` / region in the ARN |
| `ResourceNotFoundException` | Tables not created yet or wrong region. Set the same `AWS_REGION` you used before |
| `UnrecognizedClientException` / `InvalidSignature` | Wrong or expired keys; create a new access key |
| Slow dashboard | Region far away; use the nearest region. Switch back with `DB_BACKEND=sqlite` |
| Old rows mixed with new run | Press Reset (it clears all three tables) |

## Later: running on AWS instead of your laptop
Run the engine in ECS/EC2/Lambda with an **IAM role** that has the policy above attached. The code then needs no access keys at all (boto3 picks the role up automatically). Do not copy keys into servers.
Known limits to mention honestly: the `TX` and `EVT` partitions are single partitions (fine for a demo, shard by day or feeder for production), and the simulation clock itself still lives in the server process memory.
