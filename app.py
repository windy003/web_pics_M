from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, send_file, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import os
import uuid
from werkzeug.utils import secure_filename
from exif_utils import get_exif_data, modify_exif_info, get_unused_tag_id
from models import db, User, Folder, Image


# CustomTag
from datetime import datetime
from flask_migrate import Migrate
from PIL import Image as PILImage
import piexif
import json
from io import BytesIO
import base64

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # 用于flash消息
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'jpg', 'jpeg', 'png', 'gif', 'tiff'}
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 限制上传文件大小为16MB
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'tiff'}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 限制上传文件大小为16MB 

# 初始化扩展
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# 在创建 app 和 db 之后
migrate = Migrate(app, db)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# 确保上传目录存在
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# 在应用上下文中创建数据库表
with app.app_context():
    db.create_all()

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('index'))
        flash('用户名或密码错误')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if User.query.filter_by(username=username).first():
            flash('用户名已存在')
            return redirect(url_for('register'))
        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        # 创建用户的上传目录
        os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], str(user.id)), exist_ok=True)
        flash('注册成功，请登录')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    folders = Folder.query.filter_by(user_id=current_user.id).all()
    return render_template('index.html', folders=folders)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        flash('没有选择文件')
        return redirect(request.url)
    
    file = request.files['file']
    
    if file.filename == '':
        flash('没有选择文件')
        return redirect(request.url)
    
    if file and allowed_file(file.filename):
        # 生成唯一文件名，避免冲突
        original_filename = secure_filename(file.filename)
        extension = original_filename.rsplit('.', 1)[1].lower()
        unique_filename = f"{uuid.uuid4().hex}.{extension}"
        
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(filepath)
        
        flash('文件上传成功')
        return redirect(url_for('edit_exif', filename=unique_filename))
    
    flash('不支持的文件类型')
    return redirect(url_for('index'))

@app.route('/image/<int:user_id>/<int:folder_id>/<filename>')
@login_required
def uploaded_file(user_id, folder_id, filename):
    # 检查权限
    if user_id != current_user.id:
        abort(403)
    
    # 构建文件路径
    file_path = os.path.join(
        app.config['UPLOAD_FOLDER'],
        str(user_id),
        str(folder_id),
        filename
    )
    
    # 检查文件是否存在
    if not os.path.exists(file_path):
        abort(404)
    
    return send_file(file_path)

@app.route('/edit/image/<int:image_id>')
@login_required
def edit_exif(image_id):
    image = Image.query.get_or_404(image_id)
    
    # 检查权限
    if image.folder.user_id != current_user.id:
        abort(403)
    
    # 获取EXIF信息
    exif_data, tag_ids = get_exif_data(os.path.join(
        app.config['UPLOAD_FOLDER'],
        str(current_user.id),
        str(image.folder_id),
        image.filename
    ))
    
    return render_template('edit.html',
                          filename=image.filename,
                          exif_data=exif_data,
                          tag_ids=tag_ids,
                          folder_id=image.folder_id,
                          image_id=image_id)

@app.route('/api/exif/<filename>', methods=['GET'])
def get_exif(filename):
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    if not os.path.exists(filepath):
        return jsonify({'error': '文件不存在'}), 404
    
    # 获取EXIF数据
    exif_data, tag_ids = get_exif_data(filepath)
    
    # 转换为前端可用的格式
    exif_list = []
    for tag_name, value in exif_data.items():
        exif_list.append({
            'tag_name': tag_name,
            'tag_id': tag_ids.get(tag_name, ''),
            'value': str(value)
        })
    
    return jsonify(exif_list)

@app.route('/api/exif/<filename>', methods=['POST'])
@login_required
def update_exif_by_filename(filename):
    # 获取请求数据
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': '缺少数据'}), 400
    
    # 查找图片
    image = Image.query.filter_by(filename=filename).first()
    if not image:
        return jsonify({'success': False, 'error': '图片不存在'}), 404
    
    # 检查权限
    if image.folder.user_id != current_user.id:
        return jsonify({'success': False, 'error': '没有权限'}), 403
    
    # 更新EXIF信息
    try:
        # 这里添加更新EXIF的逻辑
        # 例如：更新数据库中的EXIF字段
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/exif/<int:image_id>/delete/<tag_id>', methods=['POST'])
@login_required
def delete_exif_tag(image_id, tag_id):
    image = Image.query.get_or_404(image_id)
    
    # 检查权限
    if image.folder.user_id != current_user.id:
        return jsonify({'success': False, 'error': '没有权限'}), 403
    
    # 构建文件路径
    file_path = os.path.join(
        app.config['UPLOAD_FOLDER'],
        str(current_user.id),
        str(image.folder_id),
        image.filename
    )
    
    try:
        # 读取图片
        img = PILImage.open(file_path)
        
        # 读取现有EXIF数据
        exif_dict = piexif.load(img.info.get('exif', b''))
        
        # 解析标签ID和IFD
        parts = tag_id.split('.')
        if len(parts) != 2:
            return jsonify({'success': False, 'error': '无效的标签ID'}), 400
        
        ifd, tag_id = parts
        tag_id = int(tag_id, 16)  # 将十六进制字符串转换为整数
        
        # 删除EXIF标签
        if ifd in exif_dict and tag_id in exif_dict[ifd]:
            del exif_dict[ifd][tag_id]
            
            # 将EXIF数据写回图片
            exif_bytes = piexif.dump(exif_dict)
            img.save(file_path, exif=exif_bytes)
            
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': '标签不存在'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/image/<int:image_id>/add_tag', methods=['POST'])
@login_required
def add_custom_tag(image_id):
    image = Image.query.get_or_404(image_id)
    
    # 检查权限
    if image.folder.user_id != current_user.id:
        return jsonify({'success': False, 'error': '没有权限'}), 403
    
    tag_name = request.form.get('tag_name')
    tag_value = request.form.get('tag_value')
    
    if not tag_name or not tag_value:
        return jsonify({'success': False, 'error': '标签名和值不能为空'}), 400
    
    # 创建自定义标签
    custom_tag = CustomTag(
        image_id=image_id,
        tag_name=tag_name,
        tag_value=tag_value
    )
    db.session.add(custom_tag)
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/image/<int:image_id>/delete_tag/<int:tag_id>', methods=['POST'])
@login_required
def delete_custom_tag(image_id, tag_id):
    custom_tag = CustomTag.query.get_or_404(tag_id)
    
    # 检查权限
    if custom_tag.image.folder.user_id != current_user.id:
        return jsonify({'success': False, 'error': '没有权限'}), 403
    
    db.session.delete(custom_tag)
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/image/<int:image_id>/rename', methods=['POST'])
@login_required
def rename_image(image_id):
    image = Image.query.get_or_404(image_id)
    
    # 检查权限
    if image.folder.user_id != current_user.id:
        return jsonify({'success': False, 'error': '没有权限'}), 403
    
    # 获取新名称
    data = request.get_json()
    if not data or 'name' not in data:
        return jsonify({'success': False, 'error': '缺少名称参数'}), 400
    
    new_name = data['name'].strip()
    if not new_name:
        return jsonify({'success': False, 'error': '新名称不能为空'}), 400
    
    # 更新文件名
    image.original_filename = new_name
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/image/<int:image_id>/update', methods=['POST'])
@login_required
def update_exif_by_image_id(image_id):
    image = Image.query.get_or_404(image_id)
    
    # 检查权限
    if image.folder.user_id != current_user.id:
        abort(403)
    
    # 获取表单数据
    tag_name = request.form.get('tag_name')
    tag_value = request.form.get('tag_value')
    
    if not tag_name or not tag_value:
        flash('标签名和值不能为空', 'error')
        return redirect(url_for('edit_exif', image_id=image_id))
    
    # 更新EXIF信息或自定义标签
    try:
        # 这里添加更新逻辑
        # 例如：更新数据库中的EXIF字段或添加自定义标签
        db.session.commit()
        flash('更新成功', 'success')
    except Exception as e:
        db.session.rollback()
        flash('更新失败: ' + str(e), 'error')
    
    return redirect(url_for('edit_exif', image_id=image_id))

@app.route('/folder/create', methods=['POST'])
@login_required
def create_folder():
    name = request.form.get('name')
    if not name:
        flash('文件夹名称不能为空')
        return redirect(url_for('index'))
    
    # 检查是否存在同名文件夹
    existing_folder = Folder.query.filter_by(
        user_id=current_user.id,
        name=name
    ).first()
    
    if existing_folder:
        flash('同名文件夹已存在')
        return redirect(url_for('index'))
    
    # 创建新文件夹
    folder = Folder(name=name, user_id=current_user.id)
    db.session.add(folder)
    db.session.commit()
    
    # 创建对应的物理文件夹
    folder_path = os.path.join(
        app.config['UPLOAD_FOLDER'],
        str(current_user.id),
        str(folder.id)
    )
    os.makedirs(folder_path, exist_ok=True)
    
    flash('文件夹创建成功')
    return redirect(url_for('index'))

@app.route('/folder/<int:folder_id>/delete', methods=['POST'])
@login_required
def delete_folder(folder_id):
    folder = Folder.query.get_or_404(folder_id)
    if folder.user_id != current_user.id:
        flash('没有权限删除此文件夹')
        return redirect(url_for('index'))
    
    # 删除文件夹中的所有图片
    for image in folder.images:
        file_path = os.path.join(
            app.config['UPLOAD_FOLDER'],
            str(current_user.id),
            str(folder.id),
            image.filename
        )
        if os.path.exists(file_path):
            os.remove(file_path)
    
    # 删除物理文件夹
    folder_path = os.path.join(
        app.config['UPLOAD_FOLDER'],
        str(current_user.id),
        str(folder.id)
    )
    if os.path.exists(folder_path):
        os.rmdir(folder_path)
    
    # 删除数据库记录
    db.session.delete(folder)
    db.session.commit()
    
    flash('文件夹删除成功')
    return redirect(url_for('index'))

@app.route('/folder/<int:folder_id>/rename', methods=['POST'])
@login_required
def rename_folder(folder_id):
    folder = Folder.query.get_or_404(folder_id)
    if folder.user_id != current_user.id:
        return jsonify({'error': '没有权限重命名此文件夹'}), 403
    
    new_name = request.form.get('name')
    if not new_name:
        return jsonify({'error': '文件夹名称不能为空'}), 400
    
    # 检查新名称是否已存在
    existing_folder = Folder.query.filter_by(
        user_id=current_user.id,
        name=new_name
    ).first()
    
    if existing_folder and existing_folder.id != folder_id:
        return jsonify({'error': '同名文件夹已存在'}), 400
    
    folder.name = new_name
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/folder/<int:folder_id>')
@login_required
def view_folder(folder_id):
    folder = Folder.query.get_or_404(folder_id)
    if folder.user_id != current_user.id:
        flash('没有权限访问此文件夹')
        return redirect(url_for('index'))
    
    return render_template('folder.html', folder=folder)

@app.route('/folder/<int:folder_id>/upload', methods=['POST'])
@login_required
def upload_image(folder_id):
    folder = Folder.query.get_or_404(folder_id)
    if folder.user_id != current_user.id:
        return jsonify({'error': '没有权限上传到此文件夹'}), 403
    
    if 'files' not in request.files:
        flash('没有选择文件')
        return redirect(url_for('view_folder', folder_id=folder_id))
    
    files = request.files.getlist('files')
    if not files or all(file.filename == '' for file in files):
        flash('没有选择文件')
        return redirect(url_for('view_folder', folder_id=folder_id))
    
    success_count = 0
    for file in files:
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            # 生成唯一文件名
            unique_filename = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{filename}"
            
            # 确保目录存在
            file_dir = os.path.join(
                app.config['UPLOAD_FOLDER'],
                str(current_user.id),
                str(folder_id)
            )
            os.makedirs(file_dir, exist_ok=True)
            
            # 保存文件
            file_path = os.path.join(file_dir, unique_filename)
            file.save(file_path)
            
            # 创建图片记录
            image = Image(
                filename=unique_filename,
                original_filename=filename,
                folder_id=folder_id
            )
            db.session.add(image)
            success_count += 1
    
    db.session.commit()
    flash(f'成功上传 {success_count} 张图片')
    
    return redirect(url_for('view_folder', folder_id=folder_id))

@app.route('/api/exif/<int:image_id>/add', methods=['POST'])
@login_required
def add_exif_tag(image_id):
    image = Image.query.get_or_404(image_id)
    
    # 检查权限
    if image.folder.user_id != current_user.id:
        flash('没有权限修改此图片', 'error')
        return redirect(url_for('edit_exif', image_id=image_id))
    
    # 获取表单数据 - 只获取标签值
    tag_value = request.form.get('tag_value')
    
    if not tag_value:
        flash('标签值不能为空', 'error')
        return redirect(url_for('edit_exif', image_id=image_id))
    
    # 构建文件路径
    file_path = os.path.join(
        app.config['UPLOAD_FOLDER'],
        str(current_user.id),
        str(image.folder_id),
        image.filename
    )
    
    try:
        # 读取图片
        img = PILImage.open(file_path)
        
        # 确保图片格式支持EXIF
        if img.format not in ['JPEG', 'TIFF']:
            flash(f'图片格式 {img.format} 不支持EXIF数据', 'error')
            return redirect(url_for('edit_exif', image_id=image_id))
        
        # 创建一个新的EXIF字典
        zeroth_ifd = {}
        exif_ifd = {}
        gps_ifd = {}
        
        # 尝试读取现有EXIF数据
        try:
            exif_data = img.info.get('exif')
            if exif_data:
                exif_dict = piexif.load(exif_data)
                zeroth_ifd = exif_dict.get("0th", {})
                exif_ifd = exif_dict.get("Exif", {})
                gps_ifd = exif_dict.get("GPS", {})
        except:
            # 如果读取失败，使用空字典
            pass
        
        # 直接将文本数据转换为二进制并存储在UserComment字段中
        # UserComment需要特定格式：前8字节为字符集标识符，后面为实际内容
        # 使用ASCII字符集（前8字节为ASCII\0\0\0）
        exif_ifd[piexif.ExifIFD.UserComment] = b'ASCII\0\0\0' + tag_value.encode('utf-8', errors='replace')
        
        # 创建新的EXIF字典
        exif_dict = {"0th": zeroth_ifd, "Exif": exif_ifd, "GPS": gps_ifd}
        
        # 将EXIF数据写回图片
        exif_bytes = piexif.dump(exif_dict)
        
        # 保存图片
        img.save(file_path, exif=exif_bytes)
        
        flash('EXIF标签添加成功', 'success')
    except Exception as e:
        print(f"错误: {str(e)}")
        flash(f'添加EXIF标签失败: {str(e)}', 'error')
    
    return redirect(url_for('edit_exif', image_id=image_id))

@app.route('/edit/image/<int:image_id>/update', methods=['POST'])
@login_required
def update_exif(image_id):
    image = Image.query.get_or_404(image_id)
    
    # 检查权限
    if image.folder.user_id != current_user.id:
        abort(403)
    
    # 获取表单数据
    tag_name = request.form.get('tag_name')
    tag_value = request.form.get('tag_value')
    
    if not tag_name or not tag_value:
        flash('标签名和值不能为空', 'error')
        return redirect(url_for('edit_exif', image_id=image_id))
    
    # 更新EXIF信息或自定义标签
    try:
        # 这里添加更新逻辑
        # 例如：更新数据库中的EXIF字段或添加自定义标签
        db.session.commit()
        flash('更新成功', 'success')
    except Exception as e:
        db.session.rollback()
        flash('更新失败: ' + str(e), 'error')
    
    return redirect(url_for('edit_exif', image_id=image_id))

@app.route('/folder/<int:folder_id>/image/<int:image_id>/delete', methods=['POST'])
@login_required
def delete_image(folder_id, image_id):
    # 获取图片
    image = Image.query.get_or_404(image_id)
    
    # 检查权限
    if image.folder.user_id != current_user.id:
        flash('没有权限删除此图片', 'error')
        return redirect(url_for('view_folder', folder_id=folder_id))
    
    # 检查图片是否属于指定文件夹
    if image.folder_id != folder_id:
        flash('图片不属于此文件夹', 'error')
        return redirect(url_for('view_folder', folder_id=folder_id))
    
    try:
        # 构建文件路径
        file_path = os.path.join(
            app.config['UPLOAD_FOLDER'],
            str(current_user.id),
            str(folder_id),
            image.filename
        )
        
        # 删除文件
        if os.path.exists(file_path):
            os.remove(file_path)
        
        # 删除图片记录
        db.session.delete(image)
        db.session.commit()
        
        flash('图片删除成功', 'success')
    except Exception as e:
        db.session.rollback()
        print(f"删除图片时出错: {str(e)}")
        flash(f'删除图片失败: {str(e)}', 'error')
    
    return redirect(url_for('view_folder', folder_id=folder_id))

if __name__ == '__main__':
    app.run(debug=True,port=5004,host='0.0.0.0')
