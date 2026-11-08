#!/usr/bin/env python3
"""Budget-capped Apify retrieval only. Judgment belongs to the agent's skills."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlencode

from kit_common import digest, handle, http, load, report_error, save, stamp, token
from relationships import Refusal, private_fd

BASE = 'https://api.apify.com/v2'
ACTORS = {'apidojo~twitter-user-scraper', 'apidojo~tweet-scraper'}
RUN_ID = re.compile(r'^[A-Za-z0-9]{5,64}$')


def pricing_ceiling(actor, actor_data, max_items, actor_input):
    if not isinstance(actor_data, dict):
        raise Refusal('Public actor metadata is malformed; no run started.')
    infos = actor_data.get('pricingInfos')
    if isinstance(infos, list):
        try:
            active = [(datetime.fromisoformat(p['startedAt'].replace('Z', '+00:00')), p) for p in infos]
            active = [(started, p) for started, p in active if started <= datetime.now(timezone.utc)]
            info = max(active, key=lambda pair: pair[0])[1]
        except (TypeError, ValueError, KeyError):
            raise Refusal('Live actor pricing dates are invalid or no current plan exists.') from None
    else:
        info = actor_data.get('pricingInfo')
    if not isinstance(info, dict) or info.get('pricingModel') != 'PAY_PER_EVENT':
        raise Refusal('Unknown actor pricing model; inspect current public pricing before spending.')
    per_event = info.get('pricingPerEvent', {})
    events = per_event.get('actorChargeEvents', {}) if isinstance(per_event, dict) else {}
    if not isinstance(events, dict) or not events:
        raise Refusal('Live actor event prices are missing; no run started.')
    def event_price(name):
        event = events.get(name)
        if not isinstance(event, dict):
            raise Refusal('Required live actor price event is missing.')
        tiers = event.get('eventTieredPricingUsd')
        if isinstance(tiers, dict) and tiers:
            values = [tier.get('tieredEventPriceUsd') for tier in tiers.values() if isinstance(tier, dict)]
            if len(values) != len(tiers):
                raise Refusal('Unsupported tiered actor pricing.')
        else:
            values = [event.get('eventPriceUsd')]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in values):
            raise Refusal('Unsupported actor event price; no run started.')
        return max(values)
    if actor.endswith('twitter-user-scraper'):
        allowed = {'dataset-item', 'about-event', 'retweeters-event', 'following-event',
                   'follower-event', 'single-url-event', 'keyword-search-event'}
        if set(events) - allowed:
            raise Refusal('Actor added an unknown billing event; inspect current pricing.')
        # Other declared events are inactive for our narrow handle+one-graph input.
        query_event = 'following-event' if actor_input['getFollowing'] else 'follower-event'
        ceiling = max_items * event_price('dataset-item') + event_price(query_event) + event_price('single-url-event')
    else:
        if set(events) != {'apify-default-dataset-item'}:
            raise Refusal('Tweet actor billing events changed; inspect current pricing.')
        ceiling = max_items * event_price('apify-default-dataset-item')
    return ceiling, digest(info)


def run_actor(actor, actor_input, max_items, max_cost_usd, output, resume_run_id=None,
              api=http, sleep=time.sleep, clock=time.monotonic):
    if actor not in ACTORS:
        raise Refusal('Actor is not in the retrieval allowlist.')
    if not 1 <= max_items <= 10_000 or not math.isfinite(max_cost_usd) or not 0 < max_cost_usd <= 1:
        raise Refusal('Apify requires 1..10000 items and an explicit positive cap no larger than $1.')
    if actor.endswith('twitter-user-scraper'):
        if (set(actor_input) != {'twitterHandles', 'maxItems', 'getFollowing', 'getFollowers'}
                or not isinstance(actor_input['twitterHandles'], list) or len(actor_input['twitterHandles']) != 1
                or type(actor_input['getFollowing']) is not bool or type(actor_input['getFollowers']) is not bool
                or actor_input['getFollowing'] == actor_input['getFollowers']):
            raise Refusal('Graph actor input must request one handle and exactly one graph kind.')
        handle(actor_input['twitterHandles'][0])
    elif (set(actor_input) != {'searchTerms', 'maxItems', 'sort'} or actor_input.get('sort') != 'Latest'
          or not isinstance(actor_input.get('searchTerms'), list) or len(actor_input['searchTerms']) != 1
          or not isinstance(actor_input['searchTerms'][0], str) or not 1 <= len(actor_input['searchTerms'][0]) <= 1000):
        raise Refusal('Search actor input must contain one bounded Latest query.')
    if actor_input.get('maxItems') != max_items:
        raise Refusal('Actor maxItems must equal the approved retrieval limit.')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    receipt_path = Path(str(output) + '.run.json')
    lock_fd = private_fd(str(receipt_path) + '.lock', os.O_CREAT | os.O_RDWR)
    with os.fdopen(lock_fd, 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        bearer = token('APIFY_TOKEN')
        fingerprint = digest({'actor': actor, 'input': actor_input, 'max_items': max_items,
                              'max_cost_usd': max_cost_usd})
        if resume_run_id:
            if not RUN_ID.fullmatch(resume_run_id) or not receipt_path.exists():
                raise Refusal('Resume needs the original private run receipt and valid run ID.')
            receipt = load(receipt_path)
            if receipt.get('fingerprint') != fingerprint or receipt.get('run_id') != resume_run_id:
                raise Refusal('Resume parameters do not match the original run receipt.')
            run_id = resume_run_id
        else:
            if receipt_path.exists() or output.exists():
                raise Refusal('Retrieval output/receipt already exists. Inspect it; never resubmit automatically.')
            public = api('GET', BASE + '/acts/' + actor)
            actor_data = public.get('data', {}) if isinstance(public, dict) else {}
            estimated, price_digest = pricing_ceiling(actor, actor_data, max_items, actor_input)
            if estimated > max_cost_usd + 1e-9:
                raise Refusal('Conservative live-price estimate exceeds the approved cap; no run started.')
            receipt = {'version': 1, 'actor': actor, 'fingerprint': fingerprint, 'status': 'start_intent',
                       'started_at': stamp(), 'max_cost_usd': max_cost_usd, 'max_items': max_items,
                       'pricing_sha256': price_digest, 'conservative_estimate_usd': estimated}
            save(receipt_path, receipt, exclusive=True)
            # Server-side charge cap mandatory; only this POST starts a paid run. Never retry.
            url = BASE + '/acts/' + actor + '/runs?' + urlencode({'maxTotalChargeUsd': max_cost_usd,
                      'timeout': 180})
            started = api('POST', url, bearer, actor_input)
            data = started.get('data', {}) if isinstance(started, dict) else {}
            run_id = data.get('id', '') if isinstance(data, dict) else ''
            if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
                raise Refusal('Run start outcome unresolved. Keep receipt; inspect Apify, do not submit again.')
            receipt.update(run_id=run_id, status='running')
            save(receipt_path, receipt)
        deadline = clock() + 210
        while True:
            value = api('GET', BASE + '/actor-runs/' + run_id, bearer)
            run = value.get('data', {}) if isinstance(value, dict) else {}
            if not isinstance(run, dict) or run.get('id') != run_id:
                raise Refusal('Run status identity mismatch; stopped.')
            status = run.get('status')
            if status in ('SUCCEEDED', 'FAILED', 'TIMED-OUT', 'ABORTED'):
                break
            if status not in ('READY', 'RUNNING', 'TIMING-OUT', 'ABORTING') or clock() >= deadline:
                raise Refusal('Run is incomplete or polling deadline reached. Resume original ID; never resubmit.')
            sleep(2)
        receipt['status'] = status
        save(receipt_path, receipt)
        if status != 'SUCCEEDED':
            raise Refusal('Actor did not succeed; inspect the original run. No replacement run started.')
        dataset = run.get('defaultDatasetId', '')
        if not isinstance(dataset, str) or not RUN_ID.fullmatch(dataset):
            raise Refusal('Run has no valid dataset ID.')
        items = []
        while len(items) < max_items:
            size = min(250, max_items - len(items))
            page = api('GET', BASE + '/datasets/' + dataset + '/items?' + urlencode({
                'format': 'json', 'clean': 'true', 'offset': len(items), 'limit': size}), bearer)
            if not isinstance(page, list) or len(page) > size:
                raise Refusal('Unexpected dataset response; retrieval stopped.')
            items.extend(page)
            if len(page) < size:
                break
        # Per-result prices settle after completion. Do not report early usage as final cost.
        sleep(15)
        settled = api('GET', BASE + '/actor-runs/' + run_id, bearer)
        data = settled.get('data', {}) if isinstance(settled, dict) else {}
        cost = data.get('usageTotalUsd') if isinstance(data, dict) else None
        if not isinstance(data, dict) or data.get('id') != run_id or isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0:
            raise Refusal('Settled run cost unavailable; keep receipt and inspect original run.')
        receipt.update(status='retrieved', settled_cost_usd=cost, cost_checked_at=stamp(), count=len(items))
        save(receipt_path, receipt)
        if cost > max_cost_usd + .000001:
            raise Refusal('Provider reports cost above the approved cap. Stop and inspect billing; no new run.')
        return {'actor': actor, 'run_id': run_id, 'items': items, 'max_cost_usd': max_cost_usd,
                'settled_cost_usd': cost, 'cost_checked_at': receipt['cost_checked_at'],
                'complete': False, 'coverage': 'bounded public retrieval; not proof of complete graph'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('search')
    p.add_argument('--query', required=True)
    p.add_argument('--max-items', type=int, default=50)
    p.add_argument('--max-cost-usd', type=float, default=.05)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--execute', action='store_true')
    p.add_argument('--resume-run-id')
    args = parser.parse_args(argv)
    try:
        if not 1 <= args.max_items <= 10_000 or not 0 < args.max_cost_usd <= 1 or not 1 <= len(args.query) <= 1000:
            raise Refusal('Invalid query, item limit or budget.')
        if not args.execute:
            print(json.dumps({'dry_run': True, 'network_calls': 0, 'query': args.query,
                              'max_items': args.max_items, 'max_cost_usd': args.max_cost_usd}))
            return 0
        value = run_actor('apidojo~tweet-scraper', {'searchTerms': [args.query],
                          'maxItems': args.max_items, 'sort': 'Latest'}, args.max_items,
                          args.max_cost_usd, args.output, args.resume_run_id)
        save(args.output, value)
        print(json.dumps({'output': str(args.output), 'run_id': value['run_id'],
                          'count': len(value['items']), 'settled_cost_usd': value['settled_cost_usd']}))
        return 0
    except (Refusal, OSError, ValueError, TypeError, KeyError) as exc:
        print('STOP: ' + report_error(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
