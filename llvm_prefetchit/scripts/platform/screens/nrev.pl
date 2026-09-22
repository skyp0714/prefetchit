app([],L,L).
app([H|T],L,[H|R]) :- app(T,L,R).
nrev([],[]).
nrev([H|T],R) :- nrev(T,RT), app(RT,[H],R).
range(N,N,[N]) :- !.
range(I,N,[I|T]) :- I1 is I+1, range(I1,N,T).
bench(0) :- !.
bench(K) :- range(1,400,L), nrev(L,_), K1 is K-1, bench(K1).
:- initialization((bench(20000), halt)).
