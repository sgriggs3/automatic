import tensorflow as tf

hello = tf.constant('Hello, TensorFlow!')

sess = tf.Session()

hello = tf.constant('Hello, TensorFlow!')

print(sess.run(hello))
