import importlib.util, pathlib, subprocess, textwrap, json, tempfile, os
COMP=pathlib.Path('/mnt/data/compiler_review/jcc_fixed_round2.py')
spec=importlib.util.spec_from_file_location('jcc',COMP); jcc=importlib.util.module_from_spec(spec); spec.loader.exec_module(jcc)
CASES=[]
def add(n,s,e='ok',run=True,out=None): CASES.append((n,textwrap.dedent(s),e,run,out))
add('const_class_param_negative','''
class A { $void mut() { } }
void f(const A a) { a.mut(); }
void main(string param) { A x=A(); f(x); }
''','err')
add('const_class_ptr_param_negative','''
class A { $void mut() { } }
void f(const A* a) { a.mut(); }
void main(string param) { A* x = new A(); f(x); }
''','err')
add('const_class_ptr_param_positive','''
class A { $i32 x; constr(){x=4;} $i32 read() const { return x; } }
i32 f(const A* a) { return a.read(); }
void main(string param) { A* x = new A(); sys:print(f(x)); }
''','ok',True,'4\n')
add('suffix_const_class_ptr','''
class A { $i32 x; constr(){x=1;} $void inc(){x=x+1;} }
void main(string param) { A* p = new A(); A* const q = p; q.inc(); sys:print(q.x); }
''','ok',True,'2\n')
add('duplicate_methods_same_params','''class A { $i32 f(i32 x){return x;} $f64 f(i32 x){return x;} }
void main(string param) { }''','err',False)
add('overload_resolution_float_first','''class A { $f64 f(f64 x){return x+0.5;} $i32 f(i32 x){return x+1;} }
void main(string param) { A a=A(); f64 x=a.f(2.5); sys:print(x); }''','ok',True,'3\n')
add('overload_resolution_int_first','''class A { $i32 f(i32 x){return x+1;} $f64 f(f64 x){return x+0.5;} }
void main(string param) { A a=A(); f64 x=a.f(2.5); sys:print(x); }''','ok',True,'3\n')
add('ctor_overload_choice','''class A { $i32 x; constr(){x=1;} constr(i32 v){x=v;} }
void main(string param) { A a=A(8); sys:print(a.x); }''','ok',True,'8\n')
add('ctor_default_choice','''class A { $i32 x; constr(i32 v=9){x=v;} constr(i32 v,i32 w){x=v+w;} }
void main(string param) { A a=A(); sys:print(a.x); }''','ok',True,'9\n')
add('duplicate_destructor','''class A { destr(){} destr(){} }
void main(string param) { A a=A(); }''','err',False)
add('destructor_params','''class A { destr(i32 x){} }
void main(string param) { A a=A(); }''','err',False)
add('extern_overload','''@extern i32 f(i32 x); @extern f64 f(f64 x); void main(string param){}''','err',False)
add('nested_list_rejected','''void main(string param){ list<list<i32>> x; }''','err',False)
add('map_i32_key','''void main(string param){ map<i32,string> m={1,"one",2,"two"}; sys:print(m[2]); }''','ok',True,'two\n')
add('map_f64_key','''void main(string param){ map<f64,string> m={1.5,"one",2.5,"two"}; sys:print(m[2.5]); }''','ok',True,'two\n')
add('while_true_no_fallthrough','''i32 f(){ while(true){} }
void main(string param){}''','ok',False)
add('while_true_break_negative','''i32 f(){ while(true){break;} }
void main(string param){}''','err',False)
add('loop_nested_break','''i32 f(){ loop { while(true){ break; } } }
void main(string param){}''','ok',False)
add('sibling_const_scope','''void main(string param){ if(true){ const i32 x=1; sys:print(x); } if(true){ i32 x=2; x=x+1; sys:print(x); } }''','ok',True,'1\n3\n')
add('sibling_pointee_const_scope','''void main(string param){ i32 a=1; if(true){ const i32* p=&a; } i32* p=&a; *p=3; sys:print(a); }''','ok',True,'3\n')
add('main_collision','''void main(string argc){ i32 _j_main_argc=1; i32 _j_main_argv=2; sys:print(argc); sys:print(_j_main_argc); sys:print(_j_main_argv); }''','ok',True,'hello\n1\n2\n')
add('class_function_abi','''class A { $i32 x; constr(i32 v){x=v;} }
i32 get(A a){ return a.x; }
A make(A a){ return a; }
void main(string param){ A a=A(7); A b=make(a); sys:print(get(b)); }''','ok',True,'7\n')
add('class_function_ptr_alias','''class A { $i32 x; constr(i32 v){x=v;} }
A make(A a){return a;}
using Cb = fn(A)->A;
void main(string param){ A a=A(3); Cb cb=make; A b=cb(a); sys:print(b.x); }''','ok',True,'3\n')
add('const_class_local_call','''class A { $i32 x; constr(){x=1;} $i32 read() const{return x;} $void mut(){x=x+1;} }
void main(string param){ const A a=A(); sys:print(a.read()); }''','ok',True,'1\n')
add('const_class_local_mut_negative','''class A { $void mut(){} }
void main(string param){ const A a=A(); a.mut(); }''','err')

res=[]
for n,s,e,run,expected in CASES:
    for mode in [False,True]:
        try:
            c=jcc.transpile(s,c89=mode)
            p=pathlib.Path('/mnt/data/compiler_review/fix_tests/verify_tmp.c'); p.write_text(c)
            exe=p.with_suffix('.exe'+('_c89' if mode else '_normal'))
            cmd=['gcc','-std=c89' if mode else '-std=gnu11','-w',str(p),'-lm','-o',str(exe)]
            q=subprocess.run(cmd,text=True,capture_output=True,timeout=30)
            if q.returncode: raise RuntimeError('gcc:'+q.stderr[-1000:])
            if e=='err':
                res.append({'case':n,'mode':'c89' if mode else 'normal','pass':False,'unexpected':'compiled'})
            elif run:
                a=subprocess.run([str(exe),'hello'],text=True,capture_output=True,timeout=10)
                ok=a.returncode==0 and (expected is None or a.stdout==expected)
                res.append({'case':n,'mode':'c89' if mode else 'normal','pass':ok,'stdout':a.stdout,'stderr':a.stderr,'rc':a.returncode})
            else:
                res.append({'case':n,'mode':'c89' if mode else 'normal','pass':True})
        except Exception as ex:
            if e=='err':
                res.append({'case':n,'mode':'c89' if mode else 'normal','pass':True,'diagnostic':str(ex)})
            else:
                res.append({'case':n,'mode':'c89' if mode else 'normal','pass':False,'error':str(ex)})

path='/mnt/data/compiler_review/fix_tests/verify_fixed_results.json'; json.dump(res,open(path,'w'),indent=2)
print('TOTAL',len(res),'PASS',sum(x['pass'] for x in res),'FAIL',sum(not x['pass'] for x in res))
for x in res:
 if not x['pass']: print('\nFAIL',x)
