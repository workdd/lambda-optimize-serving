# image-classification converter 

import time
import numpy as np
import os
import boto3
import torch
import hashlib

BUCKET_NAME = os.environ.get('BUCKET_NAME')
s3_client = boto3.client('s3') 


def load_model(model_name,model_size):    
    os.makedirs(os.path.dirname(f'/tmp/torch/{model_name}/'), exist_ok=True)
    s3_client.download_file(BUCKET_NAME, f'models/torch/{model_name}_{model_size}/model.pt', f'/tmp/torch/{model_name}/model.pt')
        
    PATH = f"/tmp/torch/{model_name}/"
    model = torch.load(PATH+'model.pt')

    return model

def optimize_tvm(model,model_name,batchsize,imgsize=224,layout="NHWC"):
    import tvm
    from tvm import relay

    input_shape = (batchsize, 3, imgsize, imgsize)

    data_array = np.random.uniform(0, 255, size=input_shape).astype("float32")
    torch_data = torch.tensor(data_array)

    model.eval()
    traced_model = torch.jit.trace(model, torch_data)

    convert_start_time = time.time()
    mod, params = relay.frontend.from_pytorch(traced_model, input_infos=[('input0', input_shape)],default_dtype="float32")

    if layout == "NHWC":
        desired_layouts = {"nn.conv2d": ["NHWC", "default"]}
        seq = tvm.transform.Sequential(
            [
                relay.transform.RemoveUnusedFunctions(),
                relay.transform.ConvertLayout(desired_layouts),
            ]
        )
        with tvm.transform.PassContext(opt_level=3):
            mod = seq(mod)
    else:
        assert layout == "NCHW"

    target = "llvm -mcpu=core-avx2"
    with tvm.transform.PassContext(opt_level=3,required_pass=["FastMath"]):
        mod = relay.transform.InferType()(mod)
        lib = relay.build(mod, target=target, params=params)


    os.makedirs(os.path.dirname(f'/tmp/tvm/intel/{model_name}/'), exist_ok=True)
    lib.export_library(f"/tmp/tvm/intel/{model_name}/{model_name}_{batchsize}.tar")
    print("export done :",f"{model_name}_{batchsize}.tar")
    convert_time = time.time() - convert_start_time
    


    info = f'inteltorchtvm{model_name}{batchsize}'
    # hinfo = hashlib.sha256(info.encode())
    
    s3_client.upload_file(f'/tmp/tvm/intel/{model_name}/{model_name}_{batchsize}.tar',BUCKET_NAME,f'models/tvm/intel/{info}.tar')
    print("S3 upload done")

    return convert_time
    

def lambda_handler(event, context):    
    model_name = event['model_name']
    model_size = event['model_size']
    hardware = event['hardware']
    framework = event['framework']
    optimizer = event['optimizer']
    batchsize = event['batchsize']
    user_email = event ['user_email']
    lambda_memory = event['lambda_memory']

    start_time = time.time()
    model = load_model(model_name,model_size)

    print("Hardware optimize - Torch model to TVM model")
    convert_time = optimize_tvm(model,model_name,batchsize)


    running_time = time.time() - start_time
    return {'model':model_name,'framework':framework,'hardware':hardware,'optimizer':optimizer, 'batchsize':batchsize, 'user_email':user_email,'lambda_memory':lambda_memory,'convert_time':convert_time ,'handler_time': running_time }


