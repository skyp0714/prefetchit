#!/usr/bin/env python3
"""Price covered miss samples by independently sampled call execution rates."""
import collections
import heapq


def select(rows,frequency,floor,max_sites=1024,max_hints=4096,per_site=4,min_gain=8,goal=.75):
    assert floor>0 and all(rate>=0 for rate in frequency.values())
    candidates=collections.defaultdict(set);anchors={}
    weights=[row.get('miss_weight',1.0) for row in rows]
    assert all(weight>0 for weight in weights)
    for i,row in enumerate(rows):
        anchors.setdefault(row['line'],row['target'])
        for site in row['sites']:candidates[site,row['line']].add(i)
    candidates={key:ids for key,ids in candidates.items() if len(ids)>=min_gain}
    costs={site:max(frequency.get(site,0),floor) for site,_ in candidates}
    heap=[(-sum(weights[i] for i in ids)/costs[site],site,line) for (site,line),ids in candidates.items()]
    heapq.heapify(heap);covered=set();chosen=[];sites=collections.Counter()
    while heap and len(chosen)<max_hints and len(covered)<goal*len(rows):
        _,site,line=heapq.heappop(heap)
        if sites[site]>=per_site or (not sites[site] and len(sites)>=max_sites):continue
        ids=candidates[site,line];new=ids-covered
        if len(new)<min_gain:continue
        gain=sum(weights[i] for i in new);priority=(-gain/costs[site],site,line)
        # A site's cost is fixed, so stale priorities remain upper bounds.
        # Do not make activation cost vanish after the first hint: that would
        # invalidate this lazy-greedy ordering.
        if heap and priority>heap[0]:heapq.heappush(heap,priority);continue
        chosen.append(dict(site=site,target=anchors[line],gain=len(new),observations=len(ids),
            estimated_miss_gain_per_request=gain,estimated_hint_executions_per_request=costs[site],
            sampled_call_rate=frequency.get(site,0),regularized=frequency.get(site,0)<floor))
        sites[site]+=1;covered.update(ids)
    return dict(choices=chosen,sites=len(sites),hints=len(chosen),covered=len(covered),samples=len(rows),
        settings=dict(max_sites=max_sites,max_hints=max_hints,per_site=per_site,min_gain=min_gain,goal=goal,cost_floor=floor),
        estimated_covered_misses_per_request=sum(weights[i] for i in covered),
        estimated_hint_executions_per_request=sum(costs[c['site']] for c in chosen),
        estimated_extra_jumps_per_request=sum(costs[site] for site in sites),
        rule='Greedy new sampled misses per estimated hint execution; fixed per-call-site frequency costs, explicit zero-sample regularization, separate site and hint budgets.',
        limitation='Frequency is measured on original retired call paths, omitting extra wrong-path speculative emission. These are estimates, not actual prefetched fills, hardware accuracy, optimality or E2E predictions. Added-jump and static-code costs require NOP controls.')
