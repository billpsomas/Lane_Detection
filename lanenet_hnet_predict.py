import os
import cv2
import time
import torch
import argparse
import numpy as np

from Hnet.hnet_model import HNet
from Lanenet.model import Lanenet
from utils.evaluation import process_instance_embedding
from Hnet.hnet_utils import hnet_transform_back_points_after_polyfit


def init_args():
    """

    :return:
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--image_path', type=str, help='The image path or the src image save dir')
    parser.add_argument('--lanenet_weights', type=str, help='The lanenet model weights path')
    parser.add_argument('--hnet_weights', type=str, help='The hnet model weights path')
    parser.add_argument('--output_path', type=str, help='The output dir to save the predict result')

    return parser.parse_args()


def predict(image_path, lanenet_weights, hnet_weights, output_path='./out'):
    """
    :param image_path:
    :param lanenet_weights:
    :param hnet_weights:
    :return:
    """
    assert os.path.exists(image_path), '{:s} not exist'.format(image_path)
    os.makedirs(output_path, exist_ok=True)
    t_start = time.time()
    image = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
    org_shape = image.shape

    # step1: predict from lanenet model
    # Initialize model and send it to cpu for visualization
    LaneNet_model = Lanenet(2, 4)
    LaneNet_model.load_state_dict(torch.load(lanenet_weights, map_location=torch.device('cpu')))

    image_for_lanenet = cv2.resize(image, dsize=(512, 256), interpolation=cv2.INTER_LINEAR)
    image_for_lanenet = image_for_lanenet / 127.5 - 1.0
    image_for_lanenet = torch.tensor(image_for_lanenet, dtype=torch.float)
    image_for_lanenet = np.transpose(image_for_lanenet, (2, 0, 1))

    binary_final_logits, instance_embedding = LaneNet_model(image_for_lanenet.unsqueeze(0))
    binary_img = torch.argmax(binary_final_logits, dim=1).squeeze().numpy()
    binary_img[0:65, :] = 0
    rbg_emb, cluster_result = process_instance_embedding(instance_embedding, binary_img,
                                                         distance=1.5, lane_num=4)
    rbg_emb = cv2.resize(rbg_emb, dsize=(org_shape[1], org_shape[0]), interpolation=cv2.INTER_LINEAR)
    a = 0.6
    frame = a * image[..., ::-1] / 255 + rbg_emb * (1 - a)
    frame = np.rint(frame * 255).astype(np.uint8)
    lanenet_file_path = os.path.join(output_path, "predict_lanenet.png")
    cv2.imwrite(lanenet_file_path, frame)

    # step2: fit from hnet model
    # initialize model and load its parameters
    hnet_model = HNet()
    hnet_model.load_state_dict(torch.load(hnet_weights))
    hnet_model.to(torch.device('cpu'))
    image_hnet = cv2.resize(image, (128, 64), interpolation=cv2.INTER_LINEAR)
    cluster_result_for_hnet = np.array(cluster_result, dtype=np.uint8)  # todo maybe this is not needed
    cluster_result_for_hnet = cv2.resize(cluster_result_for_hnet, dsize=(image_hnet.shape[1], image_hnet.shape[0]),
                                         interpolation=cv2.INTER_NEAREST)
    elements = np.unique(cluster_result_for_hnet)
    lanes_pts = []
    image_to_test_lane = image_hnet.copy()
    for line_idx in elements:
        if line_idx == 0:
            continue
        idx = np.where(cluster_result_for_hnet == line_idx)
        coord = np.vstack((idx[1], idx[0])).transpose()
        lanes_pts.append(coord)

        for point in coord:
            center = (int(point[0]), int(point[1]))
            cv2.circle(image_to_test_lane, center, 0, (0, 0, 255), 1)
    cv2.imwrite(os.path.join(output_path, f"lane_for_cluster_in_hnet.png"), image_to_test_lane)

    # transofrm list of numpy to list of torch
    lanes_pts = [torch.tensor(lane_pts, dtype=torch.float32) for lane_pts in lanes_pts]

    image_for_hnet_inference = torch.tensor(image_hnet, dtype=torch.float32)
    image_for_hnet_inference = np.transpose(image_for_hnet_inference, (2, 0, 1))
    image_for_hnet_inference = image_for_hnet_inference.unsqueeze(0)
    # repeat so I have 10 batch
    image_for_hnet_inference = image_for_hnet_inference.repeat(10, 1, 1, 1) # todo fix this so it doesn't have to be repeat as batch size
    lanes_transformed_back = hnet_transform_back_points_after_polyfit(image_for_hnet_inference, hnet_model, lanes_pts,
                                                                      poly_fit_order=3)
    color = [[0, 0, 0], [255, 0, 0], [0, 255, 0], [0, 0, 255], [255, 215, 0], [0, 255, 255]]
    # paint the lanes on the image
    for i, lane_pts in enumerate(lanes_transformed_back):
        for point in lane_pts:
            center = (int(point[0]), int(point[1]))
            cv2.circle(image_hnet, center, 1, color[i], -1)
    # resize to original size
    image_hnet = cv2.resize(image_hnet, dsize=(org_shape[1], org_shape[0]), interpolation=cv2.INTER_LINEAR)
    hnet_file_path = os.path.join(output_path, "predict_hnet.png")
    cv2.imwrite(hnet_file_path, image_hnet)


if __name__ == '__main__':
    # init args
    args = init_args()
    predict(args.image_path, args.lanenet_weights, args.hnet_weights, args.output_path)
