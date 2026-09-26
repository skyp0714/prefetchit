// Exact instruction-order windows. PEBS heat is supplied separately; no simulated miss labels.
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <deque>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>
struct Ins { uint64_t ip=0,line=0; unsigned kind=0; uint64_t next=0;unsigned flow=3;uint64_t destination=0; };
int main(int argc,char**argv){
 if(argc<5)return 2;
 std::string mode=argv[1];std::ifstream mapping(argv[2]);
 std::vector<Ins> ins(1);std::unordered_map<uint64_t,uint32_t> ids;
 uint32_t id;uint64_t ip,line;unsigned kind;
 std::string mapline;
 while(std::getline(mapping,mapline)){std::istringstream row(mapline);if(!(row>>id>>ip>>line>>kind))return 3;if(id!=ins.size())return 3;Ins v{ip,line,kind};row>>v.next>>v.flow>>v.destination;ins.push_back(v);ids[ip]=id;}
 if(mode=="decode"){
  std::ofstream out(argv[3],std::ios::binary);std::string s;uint64_t total=0,unknown=0,errors=0,emitted=0,invalid_edges=0;uint32_t prior=0;int lasttid=-1;
  auto emit=[&](uint32_t v){if(v||prior){out.write((char*)&v,4);++emitted;}prior=v;};
  while(std::getline(std::cin,s)){
   if(s.find("error")!=std::string::npos||s.find("LOST")!=std::string::npos){++errors;emit(0);continue;}
   if(s.find("instructions") == std::string::npos)continue;
   auto pos=s.find_last_not_of(" \t\r");if(pos==std::string::npos)continue;auto first=s.find_last_of(" \t",pos);uint64_t pc=std::strtoull(s.substr(first+1,pos-first).c_str(),nullptr,16);
   int pid=0,tid=0;if(std::sscanf(s.c_str(),"%d/%d",&pid,&tid)!=2)return 4;
   if(tid!=lasttid){emit(0);lasttid=tid;}++total;
   auto it=ids.find(pc);if(it==ids.end()){++unknown;emit(0);}else{
    if(prior){auto v=ins[prior];bool bad=(v.flow==0&&pc!=v.next)||(v.flow==1&&pc!=v.next&&pc!=v.destination)||(v.flow==2&&pc!=v.destination);if(bad){++invalid_edges;emit(0);}}
    emit(it->second);
   }
  }
  emit(0);out.close();std::ofstream stats(argv[4]);stats<<"{\"instructions\":"<<total<<",\"unknown_instructions\":"<<unknown<<",\"decode_errors\":"<<errors<<",\"invalid_control_flow_edges\":"<<invalid_edges<<",\"emitted_records\":"<<emitted<<"}\n";
  return (!total||errors||invalid_edges)?5:0;
 }
 if(mode!="pairs"||argc!=8)return 6;
 // args mapping sequence targets low high output
 std::ifstream f(argv[3],std::ios::binary|std::ios::ate);auto bytes=f.tellg();if(bytes<0||bytes%4)return 7;f.seekg(0);
 std::vector<uint32_t> seq(size_t(bytes)/4);f.read((char*)seq.data(),bytes);
 std::ifstream targetfile(argv[4]);std::unordered_map<uint64_t,uint32_t> targetids;std::vector<uint64_t> targetlines;
 while(targetfile>>line){targetids[line]=targetlines.size();targetlines.push_back(line);}
 size_t low=std::stoul(argv[5]),high=std::stoul(argv[6]);if(low==0||high<low)return 8;
 std::vector<int32_t> target_for(ins.size(),-1);for(size_t i=1;i<ins.size();i++){auto t=targetids.find(ins[i].line);if(t!=targetids.end())target_for[i]=t->second;}
 std::vector<uint64_t> freq(ins.size()),visits(targetlines.size());std::unordered_map<uint64_t,uint64_t> counts;
 uint64_t validinstructions=0,segments=0;size_t start=0;
 while(start<seq.size()){
  while(start<seq.size()&&!seq[start])++start;size_t end=start;while(end<seq.size()&&seq[end])++end;
  if(end==start){start=end+1;continue;}++segments;validinstructions+=end-start;
  std::vector<int64_t> previous(targetlines.size(),-1);std::deque<size_t> hist;uint64_t priorline=UINT64_MAX;
  for(size_t p=start;p<end;p++){
   uint32_t cur=seq[p];if(cur>=ins.size())return 9;
   while(!hist.empty()&&p-hist.front()>high)hist.pop_front();
   int32_t t=target_for[cur];bool enter=ins[cur].line!=priorline;priorline=ins[cur].line;
   if(t>=0&&enter){
    ++visits[t];int64_t prev=previous[t];
    for(auto q:hist){if(p-q<low)break;if(prev>=int64_t(q+low))continue;uint64_t key=(uint64_t(seq[q])<<32)|uint32_t(t);++counts[key];}
    previous[t]=p;
   }
   // Every observed trigger is in the denominator, including censored futures.
   // A gap or trace end contributes no assumed target hit: this is a conservative
   // probability lower bound, never conditional on staying inside the image.
   if(ins[cur].kind){++freq[cur];hist.push_back(p);}
  }
  start=end+1;
 }
 std::ofstream out(argv[7]);out<<"# instructions "<<validinstructions<<" segments "<<segments<<" low "<<low<<" high "<<high<<"\n";
 out<<"site_id\ttarget_line\thits\ttriggers\ttarget_visits\n";
 for(auto [key,n]:counts){uint32_t s=key>>32,t=uint32_t(key);if(n>freq[s])return 10;if(n>=8)out<<s<<'\t'<<targetlines[t]<<'\t'<<n<<'\t'<<freq[s]<<'\t'<<visits[t]<<'\n';}
 return 0;
}
