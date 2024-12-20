import cv2
import os
import torch
import numpy as np
import matplotlib.pyplot as plt
from PIL import Image
from sam2.build_sam import build_sam2_video_predictor

if torch.cuda.is_available():
    device = torch.device("cuda")
else:
    device = torch.device("cpu")
print(f"using device: {device}")

# Mac file path
# sam2_checkpoint = "../../sam2/sam2.1_hiera_small.pt"
# model_cfg = "../../sam2/sam2.1_hiera_s.yaml"

# Windows file path
sam2_checkpoint = "s:/AssemblyKing_project/AssemblyKing_python/sam2/sam2.1_hiera_small.pt"
model_cfg = "s:/AssemblyKing_project/AssemblyKing_python/sam2/sam2.1_hiera_s.yaml"

predictor = build_sam2_video_predictor(model_cfg, sam2_checkpoint, device=device)

def show_mask(mask, ax, obj_id=None, random_color=False):
    if random_color:
        color = np.concatenate([np.random.random(3), np.array([0.6])], axis=0)
    else:
        cmap = plt.get_cmap("tab10")
        cmap_idx = 0 if obj_id is None else obj_id
        color = np.array([*cmap(cmap_idx)[:3], 0.6])
    h, w = mask.shape[-2:]
    mask_image = mask.reshape(h, w, 1) * color.reshape(1, 1, -1)
    ax.imshow(mask_image)


def show_points(coords, labels, ax, marker_size=200):
    pos_points = coords[labels==1]
    neg_points = coords[labels==0]
    ax.scatter(pos_points[:, 0], pos_points[:, 1], color='green', marker='*', s=marker_size, edgecolor='white', linewidth=1.25)
    ax.scatter(neg_points[:, 0], neg_points[:, 1], color='red', marker='*', s=marker_size, edgecolor='white', linewidth=1.25)


def show_box(box, ax):
    x0, y0 = box[0], box[1]
    w, h = box[2] - box[0], box[3] - box[1]
    ax.add_patch(plt.Rectangle((x0, y0), w, h, edgecolor='green', facecolor=(0, 0, 0, 0), lw=2))

def save_labels(mask, idx, class_id):
    #Generate the bounding box from the mask
    img_height, img_width = mask.shape[-2:]
    mask_image = mask.reshape(img_height, img_width, 1)
    # Step 2: Find indices where mask is True
    mask_indices = np.argwhere(mask_image)

    if mask_indices.size > 0:
        # Step 3: Compute min and max indices
        min_h = mask_indices[:, 0].min()
        max_h = mask_indices[:, 0].max()
        min_w = mask_indices[:, 1].min()
        max_w = mask_indices[:, 1].max()
        
        # Normalize bounding box coordinates for YOLO format
        x_center = (min_w + max_w) / 2.0 / img_width
        y_center = (min_h + max_h) / 2.0 / img_height
        width = (max_w - min_w) / img_width
        height = (max_h - min_h) / img_height
        
        # Save the label file
        with open(label_dir+f"/{object_name}_{idx}.txt", 'w') as f:
            f.write(f"{class_id} {x_center} {y_center} {width} {height}\n")
        
    else:
        print(f"No mask detected for Frame {idx}.")
        
def sort_by_frame_idx(frame_names, target_object_name):
    def extract_frame_idx(filename):
        name, _ = os.path.splitext(filename)
        parts = name.split('_')
        if len(parts) == 2 and parts[0] == target_object_name:
            return int(parts[1])  # Extract `out_frame_idx`
        return float('inf')  # Push other objects' frames to the end

    frame_names.sort(key=extract_frame_idx)
    return frame_names

def annotation(frames_dir, output_dir, class_id):
    """
    Annotate the first two frames in a directory of images and generate bounding boxes.

    Parameters:
    - frames_dir: Directory containing image frames named from '1.jpg' to 'n.jpg'.
    - output_dir: Directory where the annotated images and labels will be saved.
    """

    # Ensure output directory exists
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Scan all JPEG frame names in the directory
    frame_names = [
        p for p in os.listdir(frames_dir)
        if os.path.splitext(p)[-1].lower() in [".jpg", ".jpeg"]
    ]
    # Sort frame names based on their numerical value
    frame_names.sort(key=lambda x: int(os.path.splitext(x)[0].split('_')[-1]))
    # Only process the first two frames
    num_frames = min(2, len(frame_names))
    frames_to_process = frame_names[:num_frames]
    
    inference_state = predictor.init_state(frames_dir)
    for idx, frame_name in enumerate(frames_to_process):

        frame_path = os.path.join(frames_dir, frame_name)
        img = Image.open(frame_path)
        # Show the frame and ask user to click points
        plt.figure(figsize=(9, 6))
        plt.title(f"Frame {frame_name}")
        plt.imshow(img)
        print(f"Please click two points on the object in Frame {frame_name}.")
        # Collect user clicks
        points = plt.ginput(n=2, timeout=0)
        plt.close()
        
        if len(points) == 0:
            print(f"No points were clicked for Frame {idx}. Skipping.")
            continue
        
        # Convert points to numpy array
        points = np.array(points, dtype=np.float32)
        labels = np.ones(len(points), dtype=np.int32)
        
        # Process the image with predictor
        _, out_obj_ids, out_mask_logits = predictor.add_new_points_or_box(
            inference_state=inference_state,
            frame_idx=idx,
            obj_id=1,
            points=points,
            labels=labels,
        )
        
        # # Extract the mask
        # mask = (out_mask_logits[0] > 0.0).cpu().numpy()
        #         # show the results on the current (interacted) frame
        # plt.figure(figsize=(9, 6))
        # plt.title(f"frame {idx}")
        # plt.imshow(img)
        # show_points(points, labels, plt.gca())
        # show_mask(mask, plt.gca(), obj_id=out_obj_ids[0])

        # run propagation throughout the video and collect the results in a dict
    video_segments = {}  # video_segments contains the per-frame segmentation results
    for out_frame_idx, out_obj_ids, out_mask_logits in predictor.propagate_in_video(inference_state):
        video_segments[out_frame_idx] = {
            out_obj_id: (out_mask_logits[i] > 0.0).cpu().numpy()
            for i, out_obj_id in enumerate(out_obj_ids)
        }

    # render the segmentation results every few frames
    vis_frame_stride = 1
    plt.close("all")
    for out_frame_idx in range(0, len(frame_names), vis_frame_stride):
        plt.figure(figsize=(6, 4))
        plt.title(f"frame {out_frame_idx}")
        plt.imshow(Image.open(os.path.join(frames_dir, frame_names[out_frame_idx])))
        for out_obj_id, out_mask in video_segments[out_frame_idx].items():
            show_mask(out_mask, plt.gca(), obj_id=out_obj_id)
            plt.savefig(ann_img_dir+f'/{object_name}_{out_frame_idx}.jpg') # save the masked images
        save_labels(out_mask, out_frame_idx, class_id)
        plt.close()
        

def extract_video_frames(video_path, output_img_dir, frame_interval=1):
    """
    Extract frames from a video file and save them as images.

    Parameters:
    - video_path: Path to the input video file.
    - output_img_dir: Directory where extracted frames will be saved.
    - frame_interval: Number of frames to skip between saves (default 1 saves every frame).
    """

    # Ensure the output directory exists
    os.makedirs(output_img_dir, exist_ok=True)

    # Initialize video capture
    vidcap = cv2.VideoCapture(video_path)
    frame_count = 0
    saved_frame_count = 0
    success = True

    while success:
        success, frame = vidcap.read()
        if not success:
            break

        if frame_count % frame_interval == 0:
            # Save the frame as an image
            frame_filename = f"{object_name}_{frame_count}.jpg"
            frame_path = os.path.join(output_img_dir, frame_filename)
            cv2.imwrite(frame_path, frame)
            saved_frame_count += 1

        frame_count += 1

    vidcap.release()
    print(f"Extracted {saved_frame_count} frames from the video.")

def visualize_annotations(image_dir, label_dir, output_dir):
    """
    Draw bounding boxes on images based on YOLO annotations and save them to the output directory.
    """
    os.makedirs(output_dir, exist_ok=True)
    image_files = [f for f in os.listdir(image_dir) if f.endswith('.jpg')]

    for image_file in image_files:
        image_path = os.path.join(image_dir, image_file)
        label_file = image_file.replace('.jpg', '.txt')
        label_path = os.path.join(label_dir, label_file)

        # Read the image
        image = cv2.imread(image_path)
        img_height, img_width, _ = image.shape

        # Read the annotation if it exists
        if os.path.exists(label_path):
            with open(label_path, 'r') as f:
                lines = f.readlines()

            for line in lines:
                class_id, x_center, y_center, width, height = map(float, line.strip().split())
                # Convert normalized coordinates back to pixel values
                x_center *= img_width
                y_center *= img_height
                width *= img_width
                height *= img_height

                # Calculate the top-left and bottom-right coordinates
                x1 = int(x_center - width / 2)
                y1 = int(y_center - height / 2)
                x2 = int(x_center + width / 2)
                y2 = int(y_center + height / 2)

                # Draw the bounding box
                cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)
                # Optionally, put class name or ID
                cv2.putText(image, str(int(class_id)), (x1, y1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (36, 255, 12), 2)

        # Save the image with bounding boxes
        output_path = os.path.join(output_dir, image_file)
        cv2.imwrite(output_path, image)


if __name__ == "__main__":
    # Example usage
    video_path = 'object_videos/push.mp4'
    object_name = 'push'
    object_class_id = 5
    video_dir = 'object_videos'
    img_dir = 'dataset/images'
    ann_img_dir = 'dataset/mask_images'
    label_dir = 'dataset/labels'
    visual_dir = 'visualizations'
    

    user_input = input("Do you want to run extract_video_frames? (y/n): ").strip().lower()
    if user_input == 'y':
        extract_video_frames(video_path, img_dir)
    elif user_input == 'n':
        print("Skipping extract video frames...")
    else:
        print("Invalid input. Please enter 'y' or 'n'.")
        
    user_input = input("Do you want to run image annotation? (y/n): ").strip().lower()
    if user_input == 'y':
        annotation(img_dir, ann_img_dir, object_class_id) # class_id start from 0
    elif user_input == 'n':
        print("Skipping image annotations...")
    else:
        print("Invalid input. Please enter 'y' or 'n'.")
        
    user_input = input("Do you want to run annotation visualization? (y/n): ").strip().lower()
    if user_input == 'y':
        visualize_annotations(img_dir, label_dir, visual_dir)
    elif user_input == 'n':
        print("Skipping annotations visualization...")
    else:
        print("Invalid input. Please enter 'y' or 'n'.")