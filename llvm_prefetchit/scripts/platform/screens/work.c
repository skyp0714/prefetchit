#include <stdio.h>
#include <stdlib.h>
#include <string.h>
/* mixed workload for gem5 SE screening: matmul + pointer chasing + qsort */
typedef struct node { struct node *next; long v; } node;
static int cmp(const void*a,const void*b){ long x=*(long*)a,y=*(long*)b; return (x>y)-(x<y); }
int main(int argc,char**argv){
  int n=argc>1?atoi(argv[1]):160; long iters=argc>2?atol(argv[2]):20;
  double *A=malloc(n*n*8),*B=malloc(n*n*8),*C=calloc(n*n,8);
  for(int i=0;i<n*n;i++){A[i]=i%17;B[i]=i%13;}
  long N=1<<16; node *nodes=malloc(N*sizeof(node)); long *keys=malloc(N*8);
  for(long i=0;i<N;i++){nodes[i].next=&nodes[(i*7919+13)%N]; nodes[i].v=i; keys[i]=(i*2654435761u)%N;}
  double acc=0; node*p=nodes;
  for(long it=0;it<iters;it++){
    for(int i=0;i<n;i++)for(int k=0;k<n;k++){double a=A[i*n+k];for(int j=0;j<n;j++)C[i*n+j]+=a*B[k*n+j];}
    for(long s=0;s<N*4;s++){p=p->next;acc+=p->v;}
    qsort(keys,N,8,cmp); acc+=keys[N/2];
  }
  printf("%f %f\n",C[n+1],acc); return 0;
}
