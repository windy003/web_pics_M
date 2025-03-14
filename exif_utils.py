from PIL import Image
from PIL.ExifTags import TAGS
import json
import os
import piexif
import base64

def get_exif_data(image_path):
    """
    获取图片的EXIF信息
    
    参数:
        image_path: 图片文件路径
    返回:
        包含EXIF信息的字典，以及标签ID映射
    """
    try:
        # 打开图片
        img = Image.open(image_path)
        
        # 检查图片格式
        if img.format not in ['JPEG', 'TIFF']:
            print(f"图片格式 {img.format} 不支持EXIF数据")
            return {}, {}
        
        # 读取EXIF数据
        exif_data = img.info.get('exif', b'')
        if not exif_data:
            return {}, {}
        
        exif_dict = piexif.load(exif_data)
        
        # 解析EXIF数据
        parsed_exif = {}
        tag_ids = {}
        
        # 处理0th IFD
        for tag_id, value in exif_dict.get('0th', {}).items():
            if tag_id in piexif.TAGS['0th']:
                tag_name = piexif.TAGS['0th'][tag_id]['name']
                if isinstance(value, bytes):
                    try:
                        value = value.decode('utf-8').strip('\x00')
                    except UnicodeDecodeError:
                        value = f"二进制数据 ({len(value)} 字节)"
                parsed_exif[tag_name] = value
                tag_ids[tag_name] = f"0th.{hex(tag_id)}"
        
        # 处理Exif IFD
        for tag_id, value in exif_dict.get('Exif', {}).items():
            if tag_id in piexif.TAGS['Exif']:
                tag_name = piexif.TAGS['Exif'][tag_id]['name']
                
                # 特殊处理UserComment标签
                if tag_id == piexif.ExifIFD.UserComment:
                    try:
                        # 跳过前8个字节（字符集标识符）
                        if len(value) > 8:
                            comment_value = value[8:].decode('utf-8', errors='replace')
                            parsed_exif['UserComment'] = comment_value
                        else:
                            parsed_exif['UserComment'] = value.decode('utf-8', errors='replace')
                        tag_ids['UserComment'] = f"Exif.{hex(tag_id)}"
                        continue
                    except Exception as e:
                        print(f"解析UserComment时出错: {str(e)}")
                        # 如果解析失败，按普通方式处理
                
                if isinstance(value, bytes):
                    try:
                        value = value.decode('utf-8').strip('\x00')
                    except UnicodeDecodeError:
                        value = f"二进制数据 ({len(value)} 字节)"
                parsed_exif[tag_name] = value
                tag_ids[tag_name] = f"Exif.{hex(tag_id)}"
        
        # 处理GPS IFD
        for tag_id, value in exif_dict.get('GPS', {}).items():
            if tag_id in piexif.TAGS['GPS']:
                tag_name = piexif.TAGS['GPS'][tag_id]['name']
                if isinstance(value, bytes):
                    try:
                        value = value.decode('utf-8').strip('\x00')
                    except UnicodeDecodeError:
                        value = f"二进制数据 ({len(value)} 字节)"
                parsed_exif[tag_name] = value
                tag_ids[tag_name] = f"GPS.{hex(tag_id)}"
        
        return parsed_exif, tag_ids
    except Exception as e:
        print(f"读取图片 {image_path} 时出错: {str(e)}")
        return {}, {}

def get_unused_tag_id(existing_ids):
    """
    获取一个未使用的标签ID
    
    参数:
        existing_ids: 已使用的标签ID列表
    返回:
        一个未使用的标签ID
    """
    # 从65000开始分配自定义标签ID
    custom_id_start = 65000
    
    # 找到一个未使用的ID
    new_id = custom_id_start
    while new_id in existing_ids:
        new_id += 1
    
    return new_id

def modify_exif_info(image_path, custom_data=None, tags_to_delete=None):
    """
    修改图片的EXIF信息
    
    参数:
        image_path: 图片路径
        custom_data: 要添加的自定义信息字典 {标签名称: 值}
        tags_to_delete: 要删除的标签ID列表
    """
    try:
        image = Image.open(image_path)
        
        # 创建新的EXIF信息
        new_exif = image.getexif()
        
        # 获取当前所有标签ID
        existing_ids = set(new_exif.keys())
        
        # 获取标签名称到ID的映射
        exif_data, tag_ids = get_exif_data(image_path)
        
        # 获取自定义标签ID到名称的映射
        custom_tag_names = {}
        if 64999 in new_exif:
            try:
                custom_tag_names = json.loads(new_exif[64999])
            except Exception:
                pass
        
        # 删除指定的标签
        if tags_to_delete:
            for tag_id in tags_to_delete:
                try:
                    tag_id = int(tag_id)
                    if tag_id in new_exif:
                        # 获取标签名称
                        if str(tag_id) in custom_tag_names:
                            tag_name = custom_tag_names[str(tag_id)]
                            # 从自定义标签映射中删除
                            del custom_tag_names[str(tag_id)]
                        else:
                            tag_name = TAGS.get(tag_id, f"Unknown-{tag_id}")
                        
                        del new_exif[tag_id]
                        print(f"已删除标签: {tag_name} (ID: {tag_id})")
                    else:
                        print(f"未找到标签ID: {tag_id}")
                except ValueError:
                    print(f"无效的标签ID: {tag_id}，请输入数字ID")
        
        # 添加新的信息
        if custom_data:
            for tag_name, value in custom_data.items():
                # 检查是否是标准EXIF标签
                standard_tag_id = None
                for k, v in TAGS.items():
                    if v == tag_name:
                        standard_tag_id = k
                        break
                
                # 如果是标准标签
                if standard_tag_id:
                    tag_id = standard_tag_id
                # 如果是已存在的自定义标签
                elif tag_name in tag_ids:
                    tag_id = tag_ids[tag_name]
                # 如果是新的自定义标签
                else:
                    tag_id = get_unused_tag_id(existing_ids)
                    existing_ids.add(tag_id)
                    # 保存自定义标签名称
                    custom_tag_names[str(tag_id)] = tag_name
                
                # 存储值
                new_exif[tag_id] = value
                print(f"已添加标签: {tag_name} (ID: {tag_id}) = {value}")
        
        # 保存自定义标签名称映射
        if custom_tag_names:
            new_exif[64999] = json.dumps(custom_tag_names)
        elif 64999 in new_exif:
            del new_exif[64999]
        
        # 保存文件
        # 获取原文件扩展名
        base_name, ext = os.path.splitext(image_path)
        # 创建临时文件，保留原扩展名
        temp_path = f"{base_name}_temp{ext}"
        image.save(temp_path, exif=new_exif.tobytes())
        
        # 关闭原图像文件
        image.close()
        
        # 替换原文件
        os.replace(temp_path, image_path)
        print(f"EXIF信息已成功更新并覆盖原文件: {image_path}")
    
    except Exception as e:
        print(f"修改EXIF信息时出错: {str(e)}")
        raise e 