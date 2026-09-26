#include <algorithm>
#include <chrono>
#include <cstdio>
#include <numeric>
#include <random>
#include <vector>
int main(){
 std::mt19937_64 rng(20260926);volatile uint64_t sink=0;
 for(size_t mib:{16,32}){
  size_t n=mib*1024*1024/64;std::vector<size_t> order(n),data(n*8);std::iota(order.begin(),order.end(),0);std::shuffle(order.begin(),order.end(),rng);
  for(size_t i=0;i<n;i++)data[order[i]*8]=order[(i+1)%n]*8;
  size_t p=0;for(size_t i=0;i<n*4;i++)p=data[p];
  for(int rep=0;rep<3;rep++){
   auto a=std::chrono::steady_clock::now();for(size_t i=0;i<4000000;i++)p=data[p];auto b=std::chrono::steady_clock::now();sink=p;
   double ns=std::chrono::duration<double,std::nano>(b-a).count()/4000000;std::printf("%zu %d %.9f\n",mib,rep,ns);
  }
 }
 return sink==UINT64_MAX;
}
