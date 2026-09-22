-module(bench).
-export([main/0]).
loop(0, S, M) -> {S, maps:size(M)};
loop(N, S, M) ->
    S2 = S + (N * 7) rem 13,
    M2 = case N rem 1000 of 0 -> maps:put(N, S2, M); _ -> M end,
    loop(N - 1, S2, M2).
main() ->
    R = loop(40000000, 0, #{}),
    io:format("~p~n", [R]).
