"""Shared profile-free graph frontier and bounded code-line selection."""


def descendants(graph, source, min_depth=1, max_depth=1):
    """Ordered unique nodes at the requested graph depths; cycles are bounded."""
    result = []
    frontier = list(dict.fromkeys(graph.get(source, [])))
    for depth in range(1, max_depth + 1):
        if depth >= min_depth:
            result.extend(node for node in frontier if node not in result)
        frontier = list(dict.fromkeys(child for node in frontier
                                     for child in graph.get(node, [])))
    return result


def code_lines(targets, sizes, lines=1, start_line=0, cap_to_size=False,
               budget=0, order='target'):
    """Select symbol-relative lines, optionally issue every entry line first."""
    groups = [[[target, 64 * line, 0]
               for line in range(start_line, start_line + lines)
               if not cap_to_size or 64 * line < sizes.get(target, 0)]
              for target in dict.fromkeys(targets)]
    if order == 'round-robin':
        result = [group[i] for i in range(lines) for group in groups if i < len(group)]
    else:
        result = [entry for group in groups for entry in group]
    return result[:budget] if budget else result
