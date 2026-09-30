#ifndef MRL_HORN_JSONL_H
#define MRL_HORN_JSONL_H
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <limits.h>
#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif
typedef struct { char *source,*text; int32_t start,end; } MrlHornJsonEvidence;
typedef struct { char *id,*subject,*predicate,*object,*modality; bool polarity; MrlHornJsonEvidence evidence; } MrlHornJsonFact;
typedef struct { MrlHornJsonFact *facts; int32_t count; const char *error; } MrlHornJsonBatch;
static void mrl_horn_json_fact_free(MrlHornJsonFact *f){free(f->id);free(f->subject);free(f->predicate);free(f->object);free(f->modality);free(f->evidence.source);free(f->evidence.text);*f=(MrlHornJsonFact){0};}
static void mrl_horn_jsonl_free(MrlHornJsonBatch*b){if(!b)return;for(int32_t i=0;i<b->count;i++)mrl_horn_json_fact_free(&b->facts[i]);free(b->facts);*b=(MrlHornJsonBatch){0};}
static FILE *mrl_horn_jsonl_open(const char *path){
#ifdef _WIN32
 int count=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,path,-1,NULL,0);if(!count)return NULL;wchar_t *wide=malloc((size_t)count*sizeof(*wide));if(!wide)return NULL;FILE *file=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,path,-1,wide,count)?_wfopen(wide,L"rb"):NULL;free(wide);return file;
#else
 return fopen(path,"rb");
#endif
}
/* Both JSONL loaders keep byte/record limits while amortizing file reads. */
typedef struct{FILE*file;size_t at,end;unsigned char buffer[65536];}MrlHornJsonReader;
static int mrl_horn_jsonl_getc(MrlHornJsonReader*r){if(r->at==r->end){r->at=0;r->end=fread(r->buffer,1,sizeof(r->buffer),r->file);if(!r->end)return EOF;}return r->buffer[r->at++];}
static void jws(const char**p){while(**p==' '||**p=='\t'||**p=='\r'||**p=='\n')++*p;}
static int jhex(char c){return c>='0'&&c<='9'?c-'0':c>='a'&&c<='f'?c-'a'+10:c>='A'&&c<='F'?c-'A'+10:-1;}
static bool jput(char**s,size_t*n,size_t*c,unsigned char v){if(*n+1>=*c){size_t q=*c?*c*2:32;char*x=realloc(*s,q);if(!x)return false;*s=x;*c=q;}(*s)[(*n)++]=(char)v;return true;}
static bool jutf(const unsigned char*s,size_t*n){size_t i=0,k=0;while(s[i]){unsigned c=s[i];int z=c<128?1:(c&0xe0)==0xc0?2:(c&0xf0)==0xe0?3:(c&0xf8)==0xf0?4:0;if(!z||(z==2&&c<0xc2)||(z==4&&c>0xf4))return false;for(int q=1;q<z;q++)if(!s[i+q]||(s[i+q]&0xc0)!=0x80)return false;if((z==3&&c==0xe0&&s[i+1]<0xa0)||(z==3&&c==0xed&&s[i+1]>=0xa0)||(z==4&&c==0xf0&&s[i+1]<0x90)||(z==4&&c==0xf4&&s[i+1]>=0x90))return false;i+=z;k++;}if(n)*n=k;return true;}
static bool jcp(char**s,size_t*n,size_t*c,uint32_t u){if(!u)return false;if(u<=127)return jput(s,n,c,u);if(u<=2047)return jput(s,n,c,192|u>>6)&&jput(s,n,c,128|u&63);if(u<=65535)return jput(s,n,c,224|u>>12)&&jput(s,n,c,128|(u>>6)&63)&&jput(s,n,c,128|u&63);return jput(s,n,c,240|u>>18)&&jput(s,n,c,128|(u>>12)&63)&&jput(s,n,c,128|(u>>6)&63)&&jput(s,n,c,128|u&63);}
static char*jstr(const char**p){jws(p);if(**p!='"')return NULL;++*p;char*s=NULL;size_t n=0,c=0;while(**p&&**p!='"'){unsigned char x=*(*p)++;if(x<32)goto bad;if(x=='\\'){x=*(*p)++;if(x=='u'){uint32_t u=0;for(int i=0;i<4;i++){int h=jhex((*p)[i]);if(h<0)goto bad;u=u*16+h;}*p+=4;if(u>=0xd800&&u<=0xdbff){if((*p)[0]!='\\'||(*p)[1]!='u')goto bad;*p+=2;uint32_t v=0;for(int i=0;i<4;i++){int h=jhex((*p)[i]);if(h<0)goto bad;v=v*16+h;}*p+=4;if(v<0xdc00||v>0xdfff)goto bad;u=0x10000+((u-0xd800)<<10)+(v-0xdc00);}else if(u>=0xdc00&&u<=0xdfff)goto bad;if(!jcp(&s,&n,&c,u))goto bad;continue;}if(x=='b')x='\b';else if(x=='f')x='\f';else if(x=='n')x='\n';else if(x=='r')x='\r';else if(x=='t')x='\t';else if(x!='"'&&x!='\\'&&x!='/')goto bad;}if(!jput(&s,&n,&c,x))goto bad;}if(**p!='"')goto bad;++*p;if(!jput(&s,&n,&c,0)||!jutf((unsigned char*)s,NULL))goto bad;return s;bad:free(s);return NULL;}
static bool jsep(const char**p,char c){jws(p);if(**p!=c)return false;++*p;return true;}
static bool jint(const char**p,int32_t*v){jws(p);const char*s=*p;if(*s=='-')++s;if(*s=='0'){if(s[1]>='0'&&s[1]<='9')return false;++s;}else{if(*s<'1'||*s>'9')return false;while(*s>='0'&&*s<='9')++s;}errno=0;char*e;long x=strtol(*p,&e,10);if(errno==ERANGE||e!=s||x<INT32_MIN||x>INT32_MAX)return false;*p=s;*v=x;return true;}
static bool jevidence(const char**p,MrlHornJsonEvidence*e){bool a=0,b=0,c=0,d=0;if(!jsep(p,'{'))return false;jws(p);if(**p=='}'){++*p;return true;}for(;;){char*k=jstr(p);if(!k||!jsep(p,':')){free(k);return false;}bool ok=1;if(!strcmp(k,"source")){if(a++)ok=0;else e->source=jstr(p),ok=e->source;}else if(!strcmp(k,"text")){if(b++)ok=0;else e->text=jstr(p),ok=e->text;}else if(!strcmp(k,"start")){if(c++)ok=0;else ok=jint(p,&e->start);}else if(!strcmp(k,"end")){if(d++)ok=0;else ok=jint(p,&e->end);}else ok=0;free(k);if(!ok)return false;jws(p);if(**p=='}'){++*p;break;}if(!jsep(p,','))return false;}size_t q=0;if(!(a&&b&&c&&d&&e->start>=0&&e->end>=e->start&&jutf((unsigned char*)e->source,&q)&&e->end<=q))return false;const unsigned char*s=(unsigned char*)e->source;size_t i=0,lo=0,hi=0;while(i<strlen(e->source)){if(lo==(size_t)e->start)break;int z=s[i]<128?1:(s[i]&0xe0)==0xc0?2:(s[i]&0xf0)==0xe0?3:4;i+=z;lo++;}size_t begin=i;while(i<strlen(e->source)&&hi<(size_t)(e->end-e->start)){int z=s[i]<128?1:(s[i]&0xe0)==0xc0?2:(s[i]&0xf0)==0xe0?3:4;i+=z;hi++;}return strlen(e->text)==i-begin&&!memcmp(e->text,s+begin,i-begin);}
static bool jfact(const char*line,MrlHornJsonFact*f){const char*p=line;bool id=0,s=0,r=0,o=0,t=0,po=0,m=0,e=0;if(!jsep(&p,'{'))return false;for(;;){char*k=jstr(&p);if(!k||!jsep(&p,':')){free(k);goto bad;}bool ok=1;if(!strcmp(k,"id")){if(id++)ok=0;else f->id=jstr(&p),ok=f->id&&*f->id;}else if(!strcmp(k,"subject")){if(s++||t)ok=0;else f->subject=jstr(&p),ok=f->subject&&*f->subject;}else if(!strcmp(k,"predicate")){if(r++||t)ok=0;else f->predicate=jstr(&p),ok=f->predicate&&*f->predicate;}else if(!strcmp(k,"object")){if(o++||t)ok=0;else f->object=jstr(&p),ok=f->object&&*f->object;}else if(!strcmp(k,"triple")){if(t++||s||r||o)ok=0;else {ok=jsep(&p,'[');if(ok)f->subject=jstr(&p),ok=f->subject&&*f->subject&&jsep(&p,',');if(ok)f->predicate=jstr(&p),ok=f->predicate&&*f->predicate&&jsep(&p,',');if(ok)f->object=jstr(&p),ok=f->object&&*f->object&&jsep(&p,']');}}else if(!strcmp(k,"polarity")){if(po++)ok=0;else {jws(&p);if(!strncmp(p,"true",4)){p+=4;f->polarity=1;}else if(!strncmp(p,"false",5)){p+=5;f->polarity=0;}else ok=0;}}else if(!strcmp(k,"modality")){if(m++)ok=0;else f->modality=jstr(&p),ok=f->modality&&(!strcmp(f->modality,"asserted")||!strcmp(f->modality,"planned")||!strcmp(f->modality,"conditional"));}else if(!strcmp(k,"evidence")){if(e++)ok=0;else ok=jevidence(&p,&f->evidence);}else ok=0;free(k);if(!ok)goto bad;jws(&p);if(*p=='}'){++p;break;}if(!jsep(&p,','))goto bad;}jws(&p);if(*p||!id||(t&&(s||r||o))||(!t&&!(s&&r&&o)))goto bad;if(!po)f->polarity=1;if(!m){f->modality=malloc(9);if(!f->modality)goto bad;memcpy(f->modality,"asserted",9);}return true;bad:mrl_horn_json_fact_free(f);return false;}
static MrlHornJsonBatch mrl_horn_jsonl_load(const char*path,size_t max,int32_t limit){MrlHornJsonBatch b={0};FILE*f=mrl_horn_jsonl_open(path);if(!f){b.error="MRL JSONL file";return b;}char*line=NULL;size_t n=0,c=0,bytes=0;int ch;MrlHornJsonReader reader={f};while((ch=mrl_horn_jsonl_getc(&reader))!=EOF){if(++bytes>max){b.error="MRL JSONL size";goto bad;}if(ch==0){b.error="MRL JSONL NUL";goto bad;}if(ch=='\n'){if(!n){b.error="MRL JSONL line";goto bad;}if(!jput(&line,&n,&c,0)){b.error="MRL JSONL allocation";goto bad;}if(b.count>=limit){b.error="MRL JSONL records";goto bad;}MrlHornJsonFact x={0};if(!jfact(line,&x)){b.error="MRL JSONL syntax";goto bad;}for(int32_t i=0;i<b.count;i++)if(!strcmp(x.id,b.facts[i].id)){mrl_horn_json_fact_free(&x);b.error="MRL JSONL duplicate id";goto bad;}MrlHornJsonFact*q=realloc(b.facts,(size_t)(b.count+1)*sizeof(*q));if(!q){mrl_horn_json_fact_free(&x);b.error="MRL JSONL allocation";goto bad;}b.facts=q;b.facts[b.count++]=x;n=0;continue;}if(!jput(&line,&n,&c,ch)){b.error="MRL JSONL allocation";goto bad;}}if(ferror(f)){b.error="MRL JSONL read";goto bad;}if(n){if(!jput(&line,&n,&c,0)){b.error="MRL JSONL allocation";goto bad;}if(b.count>=limit){b.error="MRL JSONL records";goto bad;}MrlHornJsonFact x={0};if(!jfact(line,&x)){b.error="MRL JSONL syntax";goto bad;}for(int32_t i=0;i<b.count;i++)if(!strcmp(x.id,b.facts[i].id)){mrl_horn_json_fact_free(&x);b.error="MRL JSONL duplicate id";goto bad;}MrlHornJsonFact*q=realloc(b.facts,(size_t)(b.count+1)*sizeof(*q));if(!q){mrl_horn_json_fact_free(&x);b.error="MRL JSONL allocation";goto bad;}b.facts=q;b.facts[b.count++]=x;}free(line);fclose(f);return b;bad:{const char*e=b.error;free(line);fclose(f);mrl_horn_jsonl_free(&b);b.error=e;return b;}}
#endif
